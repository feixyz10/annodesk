"""Shared CLI/API batch coordinator; only this parent process commits labels."""

import json
import os
import signal
import threading
import time
from pathlib import Path

from annodesk.detector import inspect_classes
from annodesk.devices import DevicePlan, ExecutionOptions, resolve_plan
from annodesk.events import EventLog
from annodesk.execution import ImageExecutor, file_stamp
from annodesk.inference import SegmentRequest, compute_annotation
from annodesk.lease import ProjectLease
from annodesk.models import ModelConfig, ModelRegistry
from annodesk.operations import commit_result, eligible, prepare_detection, target_task
from annodesk.storage import Project, atomic_write


def new_report(dataset: Project, body: SegmentRequest) -> dict:
    with dataset.lock:
        ids = (
            list(dict.fromkeys(body.image_ids))
            if body.image_ids is not None
            else list(dataset.entries)
        )
        if body.image_ids is not None and (not ids or any(i not in dataset.entries for i in ids)):
            raise ValueError("Choose a non-empty image range belonging to this project")
        paths = {image_id: dataset.entries[image_id]["path"] for image_id in ids}
    return {
        "operation": body.operation,
        "image_paths": paths,
        "skip_reasons": {"excluded": 0, "review_state": 0, "no_content": 0},
        "boxes_added": 0,
        "boxes_updated": 0,
        "detections_discarded": 0,
        "classes_added": 0,
        "model": body.model,
        "processed": 0,
        "completed": 0,
        "skipped": 0,
        "failed": [],
        "input_total": len(ids),
        "total": len(ids),
        "remaining": ids,
        "request": body.model_dump(),
        "prepared": False,
        "status": "running",
        "phase": "preflight",
        "cancel": False,
        "active_workers": [],
        "results": [],
        "started_at": time.time(),
    }


def run_batch(
    dataset,
    registry,
    body,
    report,
    events,
    persist,
    *,
    executor_factory=ImageExecutor,
    available=None,
    class_probe=None,
):
    project_id = dataset.metadata["id"]
    context = {"project_id": project_id, "job_id": report.get("id")}
    with dataset.lock:
        # Older persisted reports lack paths. Never depend on mutable entries
        # while recording a result (the image may have been removed externally).
        if "image_paths" not in report:
            report["image_paths"] = {
                image_id: entry["path"] for image_id, entry in dataset.entries.items()
            }
        paths = report["image_paths"]

    def class_snapshot():
        with dataset.lock:
            return sorted(
                [
                    {key: c[key] for key in ("id", "index", "name")}
                    for c in dataset.metadata["classes"]
                ],
                key=lambda c: c["index"],
            )

    def failed(image_id, annotation, error, metrics=None):
        path = paths.get(image_id, image_id)
        if error:
            report["failed"].append({"image": path, "error": error})
            events.emit(
                "ERROR",
                f"{path}: {error}",
                event_type="image_failed",
                error_code=error,
                **context,
            )
        else:
            report["processed"] += 1
            if body.operation == "detection":
                report["project_classes"] = class_snapshot()
        report.setdefault("results", []).append(
            {
                "image": path,
                "status": "failed" if error else "saved",
                "error": error,
                **(metrics or {"elapsed_seconds": 0, "attempts": 0}),
            }
        )
        for key in ("boxes_added", "boxes_updated", "detections_discarded", "classes_added"):
            report[key] = report.get(key, 0) + (metrics or {}).get(key, 0)
        report["completed"] += 1
        report["remaining"].remove(image_id)
        persist()

    try:
        if body.operation == "segmentation" and body.text:
            raise ValueError("Batch segmentation only supports single masks from existing boxes")
        # Resolve before preflight so invalid configuration never mutates labels.
        geometry = body.operation == "boxes_from_masks"
        if geometry:
            if (
                body.device_type not in ("auto", "cpu")
                or body.devices != "auto"
                or str(body.num_workers) not in ("auto", "1")
            ):
                raise ValueError(
                    "Boxes from masks is CPU geometry; GPU and multiple workers are not used"
                )
            model, weights = "", None
            plan = DevicePlan("cpu", ["cpu"], ["cpu"])
            report.update(model="", plan=plan.to_dict())
        elif report.get("frozen_config"):
            if report.get("cuda_visible_devices") != os.environ.get("CUDA_VISIBLE_DEVICES"):
                raise ValueError(
                    "CUDA_VISIBLE_DEVICES changed; start a new job to use a different device mapping"
                )
            frozen = ModelRegistry.__new__(ModelRegistry)
            frozen.path = Path(report["config_path"])
            frozen.config = ModelConfig.model_validate(report["frozen_config"])
            registry = frozen
            model = report["model"]
            weights = registry.weights(model)
            if [weights.stat().st_mtime_ns, weights.stat().st_size] != report["weights_stamp"]:
                raise ValueError("Checkpoint changed; start a new batch")
            plan = DevicePlan(**report["plan"])
        else:
            initial_registry = ModelRegistry.__new__(ModelRegistry)
            initial_registry.path = registry.path
            initial_registry.config = registry.config.model_copy(deep=True)
            registry = initial_registry.freeze()
            model = registry.entry(body.model, body.operation).id
            weights = registry.weights(model)
            plan = resolve_plan(
                ExecutionOptions(body.device_type, body.devices, str(body.num_workers)), available
            )
            config = registry.config.model_dump()
            for entry in config["models"]:
                if entry["id"] == model:
                    entry["source"] = str(registry.resolve(model))
            report.update(
                plan=plan.to_dict(),
                model=model,
                weights=str(weights),
                weights_stamp=[weights.stat().st_mtime_ns, weights.stat().st_size],
                frozen_config=config,
                config_path=str(registry.path),
                cuda_visible_devices=os.environ.get("CUDA_VISIBLE_DEVICES"),
            )
        if not geometry:
            frozen = ModelRegistry.__new__(ModelRegistry)
            frozen.path = Path(report["config_path"])
            frozen.config = ModelConfig.model_validate(report["frozen_config"])
            registry = frozen
        body = body.model_copy(update={"model": model})
        if body.operation == "detection":
            current_classes = class_snapshot()
            if "project_classes" in report and report["project_classes"] != current_classes:
                raise ValueError("Project class definitions changed; start a new batch")
            report["project_classes"] = current_classes
            names = report.get("class_names") or (class_probe or inspect_classes)(registry, model)
            body = prepare_detection(dataset, body, {int(k): v for k, v in names.items()})
            report["class_names"] = body.class_names
        report["request"] = body.model_dump()
        events.emit(
            "INFO",
            f"Model {model}: {weights}; devices={plan.devices}; workers={plan.workers}",
            event_type="device_plan",
            **context,
        )
        if len(plan.workers) < len(plan.devices):
            events.emit(
                "WARNING",
                f"Unused devices: {plan.devices[len(plan.workers) :]}",
                event_type="device_plan",
                **context,
            )
        if not report["prepared"]:
            last_checkpoint = time.monotonic()
            for image_id in list(report["remaining"]):
                if report["cancel"]:
                    break
                try:
                    with dataset.lock:
                        if image_id not in dataset.entries:
                            raise ValueError("Image removed from project during processing")
                        annotation = dataset.annotation(image_id, materialize=False)
                    if not eligible(annotation, body):
                        reason = (
                            "excluded"
                            if annotation.excluded
                            else "review_state"
                            if getattr(annotation, target_task(body) + "_review")
                            not in body.review_states
                            else "no_content"
                        )
                        report.setdefault(
                            "skip_reasons", {"excluded": 0, "review_state": 0, "no_content": 0}
                        )[reason] += 1
                        report["skipped"] += 1
                        report["remaining"].remove(image_id)
                except Exception as error:
                    failed(image_id, None, str(error))
                report["total"] = report["input_total"] - report["skipped"]
                if time.monotonic() - last_checkpoint >= 1:
                    persist()
                    last_checkpoint = time.monotonic()
            persist()
            if not report["cancel"]:
                report["prepared"] = True
        if geometry:
            report["phase"] = "running"
            persist()
            for image_id in list(report["remaining"]):
                if report["cancel"]:
                    break
                start = time.monotonic()
                try:
                    with dataset.lock:
                        if image_id not in dataset.entries:
                            raise ValueError("Image removed from project during processing")
                        annotation = dataset.annotation(image_id)
                        if not eligible(annotation, body):
                            raise ValueError(
                                "Image no longer matches the batch eligibility; start a new batch"
                            )
                        size = dataset.image_size(image_id)
                        stamp = file_stamp(dataset.image_path(image_id))
                    result = compute_annotation(
                        dataset.image_path(image_id), size, annotation, body, None
                    )
                    if file_stamp(dataset.image_path(image_id)) != stamp:
                        raise ValueError("Image changed during processing")
                    result = commit_result(dataset, image_id, result, body)
                    failed(
                        image_id,
                        result,
                        None,
                        {
                            **result.operation_stats,
                            "elapsed_seconds": round(time.monotonic() - start, 3),
                            "attempts": 1,
                        },
                    )
                except Exception as error:
                    failed(image_id, None, str(error))
        if not geometry and report["remaining"] and not report["cancel"]:
            report["phase"] = "loading"
            persist()
            events.emit(
                "INFO",
                f"Batch loading {len(plan.workers)} workers; {report['total']} images require processing",
                event_type="batch_start",
                **context,
            )
            if [weights.stat().st_mtime_ns, weights.stat().st_size] != report["weights_stamp"]:
                raise ValueError("Checkpoint changed while preparing the batch")
            executor = executor_factory(registry, model, plan, events.bind(**context))
            executor.expected_names = body.class_names if body.operation == "detection" else None
            executor.start()
            report["phase"] = "running"
            persist()

            def activity(workers):
                report["active_workers"] = workers

            executor.run(
                dataset, list(report["remaining"]), body, failed, lambda: report["cancel"], activity
            )
        report["status"] = "cancelled" if report["cancel"] else "complete"
        report["phase"] = report["status"]
        events.emit(
            "WARNING" if report["cancel"] else "SUCCESS",
            f"Batch {report['status']}: {report['completed']}/{report['total']} finished · {report['processed']} succeeded · {len(report['failed'])} failed · {report['skipped']} skipped",
            event_type="batch_complete",
            **context,
        )
    except BaseException as error:
        report.update(
            status="interrupted" if isinstance(error, KeyboardInterrupt) else "failed",
            phase="stopped",
            error=str(error),
        )
        events.emit("CRITICAL", f"Batch stopped: {error}", event_type="batch_fatal", **context)
        raise
    finally:
        report["active_workers"] = []
        report["elapsed_seconds"] = round(time.time() - report["started_at"], 2)
        persist()


def segment_dataset(
    project: Path,
    model: str,
    registry: ModelRegistry | None,
    options: ExecutionOptions | None = None,
    events: EventLog | None = None,
    *,
    executor_factory=ImageExecutor,
    available=None,
    request: SegmentRequest | None = None,
    class_probe=None,
) -> dict:
    if request is None or request.operation != "boxes_from_masks":
        registry.weights(
            model or registry.entry("", request.operation if request else "segmentation").id
        )
    events = events or EventLog()
    options = options or ExecutionOptions()
    with ProjectLease(project):
        dataset = Project(project)
        events.emit(
            "INFO",
            f"Project write lease acquired: {dataset.root}",
            event_type="project_lock",
            project_id=dataset.metadata["id"],
        )
        body = request or SegmentRequest(model=model, **options.__dict__)
        report = new_report(dataset, body)
        report_path = (
            dataset.private
            / {
                "segmentation": "segment-report.json",
                "detection": "detect-report.json",
                "boxes_from_masks": "boxes-from-masks-report.json",
            }[body.operation]
        )

        def persist():
            atomic_write(report_path, json.dumps(report, indent=2))

        previous_handler = None
        interrupts = 0

        def interrupt(_signal, _frame):
            nonlocal interrupts
            interrupts += 1
            if interrupts > 1:
                raise KeyboardInterrupt
            report["cancel"] = True
            events.emit(
                "WARNING",
                "Cancellation requested; finishing active images. Press Ctrl+C again to terminate.",
                event_type="batch_cancel",
            )

        if threading.current_thread() is threading.main_thread():
            previous_handler = signal.signal(signal.SIGINT, interrupt)
        try:
            run_batch(
                dataset,
                registry,
                body,
                report,
                events,
                persist,
                executor_factory=executor_factory,
                available=available,
                class_probe=class_probe,
            )
        finally:
            if previous_handler is not None:
                signal.signal(signal.SIGINT, previous_handler)
        return report
