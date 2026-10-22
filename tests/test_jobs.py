import time

from annodesk.inference import SegmentationService, SegmentRequest, UltralyticsAdapter
from annodesk.jobs import BatchJobs
from annodesk.storage import Project
from tests.fakes import executor
from tests.test_batch import dataset


def wait(job):
    for _ in range(500):
        if job["status"] != "running":
            return
        time.sleep(0.01)
    raise AssertionError(f"Job did not finish: {job}")


def test_batch_progress_survives_manager_restart(tmp_path):
    registry = dataset(tmp_path)
    project = Project(tmp_path)
    service = SegmentationService(project, adapter=UltralyticsAdapter(registry))
    manager = BatchJobs(service, executor_factory=executor, available={"cuda": 0, "mps": False})
    job = manager.start(SegmentRequest())
    wait(job)
    assert job["status"] == "complete" and not job["failed"]
    restored = BatchJobs(service)
    assert restored.records[job["id"]]["completed"] == 1
    assert project.annotation(project.images()[0]["id"]).instances[0].mask
    manager.close()
    service.close()


def test_export_progress(tmp_path):
    registry = dataset(tmp_path, count=3)
    project = Project(tmp_path)
    service = SegmentationService(project, adapter=UltralyticsAdapter(registry))
    manager = BatchJobs(service)
    job = manager.export("detection", "yolo", True)
    wait(job)
    assert job["status"] == "complete"
    assert job["completed"] == job["total"] == 3
    assert job["output"]
    manager.close()
    service.close()
