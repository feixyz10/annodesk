"""Persistent background segmentation and export jobs with explicit progress phases."""

import json
import threading
import time

from annodesk.batch import new_report, run_batch
from annodesk.domain import uid
from annodesk.events import EventLog
from annodesk.inference import SegmentationService, SegmentRequest
from annodesk.storage import atomic_write


class BatchJobs:
    def __init__(
        self, service: SegmentationService, events=None, executor_factory=None, available=None
    ):
        self.service = service
        self.events = events or EventLog()
        self.executor_factory, self.available = executor_factory, available
        self.lock = threading.RLock()
        self.records = {}
        self.threads = []
        for path in sorted(
            (service.project.private / "jobs").glob("*.json"), key=lambda path: path.stat().st_mtime
        ):
            record = json.loads(path.read_text())
            if record["status"] == "running":
                record["status"] = "interrupted"
            self.records[record["id"]] = record

    def persist(self, job: dict):
        atomic_write(self.service.project.private / "jobs" / f"{job['id']}.json", json.dumps(job))

    def start(self, body: SegmentRequest, job_id: str | None = None) -> dict:
        with self.lock:
            if any(r["status"] == "running" for r in self.records.values()):
                raise ValueError("A batch is already running; cancel it before starting another")
            if job_id:
                job = self.records[job_id]
                if job.get("kind", "segmentation") == "export" or not job.get("remaining"):
                    raise ValueError("This job has no pending segmentation images")
                # Old release jobs cannot be safely mapped to new counter semantics.
                if "prepared" not in job:
                    raise ValueError("Start a new batch to continue a job from an older version")
            else:
                job = {
                    "id": uid(),
                    "kind": body.operation,
                    **new_report(self.service.project, body),
                }
            job.pop("error", None)
            job.update(
                status="running",
                phase="preflight" if not job["prepared"] else "loading",
                cancel=False,
            )
            self.records[job["id"]] = job
            self.persist(job)
            self.events.emit(
                "INFO",
                "Batch resumed" if job_id else "Batch requested",
                event_type="batch_resume" if job_id else "batch_requested",
                project_id=self.service.project.metadata["id"],
                job_id=job["id"],
            )
        thread = threading.Thread(target=self.run, args=(job,), daemon=True)
        self.threads.append(thread)
        thread.start()
        return job

    def run(self, job):
        try:
            kwargs = {"available": self.available}
            if self.executor_factory:
                kwargs["executor_factory"] = self.executor_factory
            run_batch(
                self.service.project,
                self.service.registry or self.service.adapter.registry,
                SegmentRequest.model_validate(job["request"]),
                job,
                self.events,
                lambda: self.persist(job),
                **kwargs,
            )
        except Exception as error:
            if job["status"] == "running":
                job.update(status="failed", error=str(error))
                self.persist(job)
            # run_batch has already persisted/logged the actionable error.

    def export(self, task, format, include_pending):
        from annodesk.lifecycle import export_project

        with self.lock:
            if any(r["status"] == "running" for r in self.records.values()):
                raise ValueError("Wait for the current batch before exporting")
            job = {
                "id": uid(),
                "kind": "export",
                "request": {"task": task, "format": format, "include_pending": include_pending},
                "started_at": time.time(),
                "status": "running",
                "phase": "preparing",
                "completed": 0,
                "processed": 0,
                "skipped": 0,
                "total": len(self.service.project.entries),
                "failed": [],
                "cancel": False,
                "remaining": [],
            }
            self.records[job["id"]] = job
            self.persist(job)

        def run():
            try:
                job["phase"] = "running"

                def progress(completed, total, phase="running"):
                    job.update(completed=completed, total=total, phase=phase)
                    self.persist(job)

                output = export_project(
                    self.service.project,
                    task,
                    format,
                    include_pending,
                    progress=progress,
                    cancelled=lambda: job["cancel"],
                )
                job.update(status="complete", phase="complete", output=str(output))
                self.events.emit(
                    "SUCCESS",
                    f"Export saved: {output}",
                    event_type="export_complete",
                    project_id=self.service.project.metadata["id"],
                    job_id=job["id"],
                )
            except Exception as error:
                job.update(
                    status="cancelled" if job["cancel"] else "failed",
                    phase="stopped",
                    error=str(error),
                )
                self.events.emit(
                    "ERROR",
                    f"Export stopped: {error}",
                    event_type="export_failed",
                    project_id=self.service.project.metadata["id"],
                )
            finally:
                job["elapsed_seconds"] = round(time.time() - job["started_at"], 2)
                self.persist(job)

        thread = threading.Thread(target=run, daemon=True)
        self.threads.append(thread)
        thread.start()
        return job

    def cancel(self, job_id):
        record = self.records[job_id]
        if record["status"] != "running":
            raise ValueError("Job is not running")
        record["cancel"] = True
        self.events.emit(
            "WARNING",
            "Cancellation requested; waiting for active images",
            event_type="batch_cancel",
            project_id=self.service.project.metadata["id"],
            job_id=record["id"],
        )
        self.persist(record)
        return record

    def close(self):
        for job in self.records.values():
            if job["status"] == "running":
                job["cancel"] = True
        # Keep the project lease until every writer has stopped.
        for thread in self.threads:
            thread.join()
