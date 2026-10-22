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


def test_removed_inflight_image_is_recorded_without_stopping_spawn_batch(tmp_path):
    import os

    from annodesk.lifecycle import trash_excluded
    from tests.fakes import gated_executor

    registry = dataset(tmp_path, count=2)
    project = Project(tmp_path)
    first, second = project.images()
    service = SegmentationService(project, adapter=UltralyticsAdapter(registry))
    manager = BatchJobs(
        service, executor_factory=gated_executor, available={"cuda": 0, "mps": False}
    )
    try:
        job = manager.start(SegmentRequest(device_type="cpu", num_workers="1"))
        entered = tmp_path / "worker-entered"
        deadline = time.monotonic() + 10
        while not entered.exists():
            assert time.monotonic() < deadline, job
            time.sleep(0.01)
        assert int(entered.read_text()) != os.getpid()  # A real spawn child, no simulated executor.
        annotation = project.annotation(first["id"])
        annotation.excluded = True
        project.save(first["id"], annotation)
        # Bypass the HTTP admission guard to exercise defensive result accounting.
        trash_excluded(project)
        assert first["id"] not in project.entries
        (tmp_path / "worker-release").touch()
        wait(job)
        assert job["status"] == "complete", job
        assert job["completed"] == job["total"] == 2
        assert job["processed"] == 1
        assert len(job["failed"]) == 1
        assert job["failed"][0]["image"] == first["path"]
        assert "Image removed" in job["failed"][0]["error"]
        assert job["results"][0]["image"] == first["path"]
        assert job["results"][1]["image"] == second["path"]
        assert job["remaining"] == []
        assert project.annotation(second["id"]).instances[0].mask
        persisted = manager.records[job["id"]]
        assert persisted["image_paths"][first["id"]] == first["path"]
    finally:
        (tmp_path / "worker-release").touch()
        manager.close()
        service.close()
