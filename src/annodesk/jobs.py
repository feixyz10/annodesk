"""Persistent batch progress; one queued image leaves room for interactive requests."""

import json
import threading

from annodesk.domain import uid
from annodesk.inference import SegmentationService, SegmentRequest
from annodesk.storage import atomic_write


class BatchJobs:
    def __init__(self, service: SegmentationService):
        self.service = service
        self.lock = threading.RLock()
        self.records = {}
        for path in (service.project.private / "jobs").glob("*.json"):
            record = json.loads(path.read_text())
            if record["status"] == "running":
                record["status"] = "interrupted"
            self.records[record["id"]] = record

    def persist(self, job: dict):
        atomic_write(self.service.project.private / "jobs" / f"{job['id']}.json", json.dumps(job))

    def start(self, body: SegmentRequest, job_id: str | None = None) -> dict:
        with self.lock:
            if any(record["status"] == "running" for record in self.records.values()):
                raise ValueError("A batch is already running; cancel it before starting another")
            job = (
                self.records[job_id]
                if job_id
                else {
                    "id": uid(),
                    "completed": 0,
                    "skipped": 0,
                    "failed": [],
                    "total": len(self.service.project.entries),
                    "remaining": list(self.service.project.entries),
                    "request": body.model_dump(),
                }
            )
            job.update(status="running", cancel=False)
            self.records[job["id"]] = job
            self.persist(job)
        threading.Thread(target=self.run, args=(job,), daemon=True).start()
        return job

    def run(self, job: dict):
        while job["remaining"]:
            if job["cancel"]:
                break
            image_id = job["remaining"][0]
            try:
                with self.service.project.lock:
                    annotation = self.service.project.annotation(image_id)
                if annotation.excluded or not any(
                    o.box and not o.mask and not o.polygons and not o.locked
                    for o in annotation.instances
                ):
                    job["skipped"] += 1
                else:
                    request = SegmentRequest.model_validate(job["request"])
                    self.service.executor.submit(self.service.process, image_id, request).result()
            except Exception as error:
                job["failed"].append({"image": image_id, "error": str(error)})
            job["remaining"].pop(0)
            job["completed"] += 1
            self.persist(job)
        job["status"] = "cancelled" if job["cancel"] else "complete"
        self.persist(job)

    def cancel(self, job_id: str) -> dict:
        record = self.records[job_id]
        record["cancel"] = True
        self.persist(record)
        return record
