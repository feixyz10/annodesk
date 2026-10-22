"""Shared CLI/API batch coordinator; only this parent process commits labels."""

import json
import os
import signal
import threading
import time
from pathlib import Path

from annodesk.devices import DevicePlan, ExecutionOptions, resolve_plan
from annodesk.events import EventLog
from annodesk.execution import ImageExecutor, eligible
from annodesk.inference import SegmentRequest
from annodesk.lease import ProjectLease
from annodesk.models import ModelConfig, ModelRegistry
from annodesk.storage import Project, atomic_write


def new_report(dataset: Project, body: SegmentRequest) -> dict:
    return {
        "model": body.model,
        "processed": 0,
        "completed": 0,
        "skipped": 0,
        "failed": [],
        "input_total": len(dataset.entries),
        "total": len(dataset.entries),
        "remaining": list(dataset.entries),
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
):
    project_id = dataset.metadata["id"]
    context = {"project_id": project_id, "job_id": report.get("id")}

    def failed(image_id, annotation, error, metrics=None):
        if error:
            report["failed"].append({"image": dataset.entries[image_id]["path"], "error": error})
            events.emit(
                "ERROR",
                f"{dataset.entries[image_id]['path']}: {error}",
                event_type="image_failed",
                error_code=error,
                **context,
            )
        else:
            report["processed"] += 1
        report.setdefault("results", []).append(
            {
                "image": dataset.entries[image_id]["path"],
                "status": "failed" if error else "saved",
                "error": error,
                **(metrics or {"elapsed_seconds": 0, "attempts": 0}),
            }
        )
        report["completed"] += 1
        report["remaining"].remove(image_id)
        persist()

    try:
        # Resolve before preflight so invalid configuration never mutates labels.
        if report.get("frozen_config"):
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
            registry = initial_registry
            model = registry.entry(body.model).id
            weights = registry.weights(model)
            plan = resolve_plan(
                ExecutionOptions(body.device_type, body.devices, str(body.num_workers)), available
            )
            config = registry.config.model_dump()
            for entry in config["models"]:
                if entry["id"] == model:
                    entry["source"] = str(weights.parent)
            report.update(
                plan=plan.to_dict(),
                model=model,
                weights=str(weights),
                weights_stamp=[weights.stat().st_mtime_ns, weights.stat().st_size],
                frozen_config=config,
                config_path=str(registry.path),
                cuda_visible_devices=os.environ.get("CUDA_VISIBLE_DEVICES"),
            )
        frozen = ModelRegistry.__new__(ModelRegistry)
        frozen.path = Path(report["config_path"])
        frozen.config = ModelConfig.model_validate(report["frozen_config"])
        registry = frozen
        body = body.model_copy(update={"model": model})
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
                        annotation = dataset.annotation(image_id)
                    if not eligible(annotation):
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
        if report["remaining"] and not report["cancel"]:
            report["phase"] = "loading"
            persist()
            events.emit(
                "INFO",
                f"Batch loading {len(plan.workers)} workers; {report['total']} images require segmentation",
                event_type="batch_start",
                **context,
            )
            if [weights.stat().st_mtime_ns, weights.stat().st_size] != report["weights_stamp"]:
                raise ValueError("Checkpoint changed while preparing the batch")
            executor = executor_factory(registry, model, plan, events.bind(**context))
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
    registry: ModelRegistry,
    options: ExecutionOptions | None = None,
    events: EventLog | None = None,
    *,
    executor_factory=ImageExecutor,
    available=None,
) -> dict:
    registry.weights(model)
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
        body = SegmentRequest(model=model, **options.__dict__)
        report = new_report(dataset, body)
        report_path = dataset.private / "segment-report.json"

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
            )
        finally:
            if previous_handler is not None:
                signal.signal(signal.SIGINT, previous_handler)
        return report
