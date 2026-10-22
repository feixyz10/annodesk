"""Spawned image workers with bounded dispatch and a single revision-aware writer."""

import multiprocessing as mp
import os
import queue
import signal
import time
from dataclasses import dataclass
from pathlib import Path

from annodesk.devices import DevicePlan
from annodesk.domain import Annotation
from annodesk.inference import SegmentRequest, UltralyticsAdapter, compute_annotation
from annodesk.models import ModelConfig, ModelRegistry
from annodesk.operations import commit_result
from annodesk.storage import RevisionConflict


class StartupError(ValueError):
    pass


def eligible(annotation):
    return not annotation.excluded and any(
        o.box and not o.mask and not o.polygons and not o.locked for o in annotation.instances
    )


def file_stamp(path):
    stat = path.stat()
    return (stat.st_mtime_ns, stat.st_size)


def _worker(
    worker_id,
    device,
    config,
    config_path,
    model,
    weights,
    stamp,
    inbox,
    results,
    factory,
    worker_count,
):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    # Never install global logger sinks or construct a Project in a child process.
    try:
        # Budget nested libraries before importing PyTorch in this spawned process.
        threads = max(1, (os.cpu_count() or 1) // max(1, worker_count))
        for name in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS"):
            os.environ[name] = str(threads if device == "cpu" else 1)
        registry = ModelRegistry.__new__(ModelRegistry)
        registry.path = Path(config_path)
        registry.config = ModelConfig.model_validate(config)
        if file_stamp(Path(weights)) != stamp:
            raise ValueError("Model checkpoint changed after the job was planned")
        adapter = factory(registry, device)
        names = adapter.load(model)
        results.put(("ready", worker_id, names))
    except Exception as error:
        results.put(("startup_error", worker_id, str(error)))
        return
    while True:
        task = inbox.get()
        if task is None:
            return
        image_id, path, size, annotation, body = task
        try:
            if file_stamp(Path(weights)) != stamp:
                raise ValueError("Model checkpoint changed after the job was planned")
            updated = compute_annotation(
                Path(path),
                size,
                Annotation.model_validate(annotation),
                SegmentRequest.model_validate(body),
                adapter,
            )
            if file_stamp(Path(weights)) != stamp:
                raise ValueError("Model checkpoint changed during processing")
            results.put(
                (
                    "result",
                    worker_id,
                    (
                        image_id,
                        {**updated.model_dump(), "operation_stats": updated.operation_stats},
                        None,
                    ),
                )
            )
        except Exception as error:
            results.put(("result", worker_id, (image_id, None, str(error))))


@dataclass
class Worker:
    process: object
    inbox: object
    task: tuple | None = None
    started: float = 0
    ready: bool = False


class ImageExecutor:
    def __init__(
        self,
        registry: ModelRegistry,
        model: str,
        plan: DevicePlan,
        events,
        *,
        adapter_factory=UltralyticsAdapter,
    ):
        self.context = mp.get_context("spawn")
        self.results = self.context.Queue(maxsize=max(1, len(plan.workers)))
        self.registry, self.model, self.plan, self.events = registry, model, plan, events
        self.factory = adapter_factory
        self.workers = {}
        self.weights = registry.weights(model)
        self.stamp = file_stamp(self.weights)
        self.config = registry.config.model_dump()
        # Freeze all paths before spawning: a config reload cannot change an active job.
        for entry in self.config["models"]:
            if entry["id"] == model:
                entry["source"] = str(registry.resolve(model))
        self.closed = False
        self.expected_names = None

    def spawn(self, worker_id):
        inbox = self.context.Queue(maxsize=1)
        process = self.context.Process(
            target=_worker,
            args=(
                worker_id,
                self.plan.workers[worker_id],
                self.config,
                str(self.registry.path),
                self.model,
                str(self.weights),
                self.stamp,
                inbox,
                self.results,
                self.factory,
                len(self.plan.workers),
            ),
            daemon=True,
        )
        process.start()
        self.workers[worker_id] = Worker(process, inbox)

    def start(self):
        try:
            for worker_id in range(len(self.plan.workers)):
                self.spawn(worker_id)
            deadline = time.monotonic() + 300
            while not all(w.ready for w in self.workers.values()):
                if time.monotonic() > deadline:
                    raise StartupError("Workers timed out while loading the model")
                try:
                    kind, worker_id, payload = self.results.get(timeout=0.2)
                except queue.Empty:
                    if any(not w.process.is_alive() for w in self.workers.values()):
                        raise StartupError("A worker exited during model loading") from None
                    continue
                if kind == "startup_error":
                    raise StartupError(f"Worker {worker_id}: {payload}")
                if self.expected_names is not None and payload != self.expected_names:
                    raise StartupError("Model classes changed after the task was planned")
                self.workers[worker_id].ready = True
            self.names = payload if isinstance(payload, dict) else None
            self.events.emit(
                "INFO",
                f"{len(self.workers)} workers READY · {self.model} · {self.plan.workers}",
                event_type="workers_ready",
            )
        except BaseException:
            self.close()
            raise

    def run(
        self,
        project,
        image_ids,
        body,
        on_result,
        cancelled=lambda: False,
        on_activity=lambda _: None,
    ):
        pending = iter(image_ids)
        exhausted = False
        retry_counts = {}
        retries = []
        try:
            while True:
                stopping = cancelled()
                for worker_id, worker in list(self.workers.items()):
                    if not worker.process.is_alive():
                        old_task = worker.task
                        worker.inbox.cancel_join_thread()
                        worker.inbox.close()
                        worker.process.join()
                        del self.workers[worker_id]
                        if old_task:
                            image_id = old_task[0]
                            if retry_counts.get(image_id, 0) < 1 and not stopping:
                                retry_counts[image_id] = 1
                                retries.append(old_task)
                                self.events.emit(
                                    "WARNING",
                                    f"Worker {worker_id} exited; retrying {old_task[1]} once",
                                    event_type="worker_crash",
                                    project_id=project.metadata["id"],
                                )
                            else:
                                on_result(
                                    image_id,
                                    None,
                                    "Worker exited during inference",
                                    {
                                        "elapsed_seconds": round(
                                            time.monotonic() - worker.started, 3
                                        ),
                                        "attempts": retry_counts.get(image_id, 0) + 1,
                                    },
                                )
                        continue
                    if not worker.ready or worker.task or stopping:
                        continue
                    if retries:
                        task = retries.pop(0)
                    else:
                        try:
                            image_id = next(pending)
                        except StopIteration:
                            exhausted = True
                            continue
                        try:
                            with project.lock:
                                if image_id not in project.entries:
                                    raise RevisionConflict(
                                        "Image removed from project during processing"
                                    )
                                ann = project.annotation(image_id)
                                from annodesk.operations import eligible

                                if not eligible(ann, body):
                                    raise RevisionConflict(
                                        "Image no longer matches the batch eligibility; start a new batch"
                                    )
                                task = (
                                    image_id,
                                    str(project.image_path(image_id)),
                                    project.image_size(image_id),
                                    ann.model_dump(),
                                    body.model_dump(),
                                    file_stamp(project.image_path(image_id)),
                                )
                        except Exception as error:
                            on_result(image_id, None, str(error))
                            continue
                    worker.task, worker.started = task, time.monotonic()
                    worker.inbox.put(task[:5])
                busy = [w for w in self.workers.values() if w.task]
                on_activity(
                    [
                        {
                            "worker_id": i,
                            "device": self.plan.workers[i],
                            "image": w.task[0],
                            "elapsed_seconds": round(time.monotonic() - w.started, 1),
                        }
                        for i, w in self.workers.items()
                        if w.task
                    ]
                )
                if not self.workers:
                    raise StartupError("All workers exited; processing stopped")
                if not busy and (stopping or (exhausted and not retries)):
                    break
                try:
                    kind, worker_id, result = self.results.get(timeout=0.2)
                except queue.Empty:
                    continue
                if kind != "result" or worker_id not in self.workers:
                    continue
                worker = self.workers[worker_id]
                task, worker.task = worker.task, None
                image_id, annotation, error = result
                if annotation is not None:
                    try:
                        with project.lock:
                            if image_id not in project.entries:
                                raise RevisionConflict(
                                    "Image removed from project during processing"
                                )
                            if file_stamp(self.weights) != self.stamp:
                                raise RevisionConflict("Model checkpoint changed during processing")
                            if file_stamp(project.image_path(image_id)) != task[5]:
                                raise RevisionConflict("Image changed during inference")
                            annotation = commit_result(
                                project, image_id, Annotation.model_validate(annotation), body
                            )
                    except Exception as failure:
                        annotation, error = None, str(failure)
                on_result(
                    image_id,
                    annotation,
                    error,
                    {
                        "elapsed_seconds": round(time.monotonic() - worker.started, 3),
                        "attempts": retry_counts.get(image_id, 0) + 1,
                        **(annotation.operation_stats if annotation is not None else {}),
                    },
                )
        finally:
            self.close()

    def close(self):
        if self.closed:
            return
        self.closed = True
        for worker in self.workers.values():
            if worker.process.is_alive():
                worker.process.terminate()
            worker.process.join(timeout=5)
            worker.inbox.cancel_join_thread()
            worker.inbox.close()
        self.results.cancel_join_thread()
        self.results.close()
