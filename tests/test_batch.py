import json
from functools import partial

import pytest
from PIL import Image

from annodesk.batch import segment_dataset
from annodesk.cli import segment
from annodesk.devices import ExecutionOptions
from annodesk.models import ModelRegistry
from annodesk.storage import Project
from tests.fakes import executor


def dataset(root, model="test", count=1):
    (root / "images/train/nested").mkdir(parents=True)
    (root / "labels/train/nested").mkdir(parents=True)
    for i in range(count):
        Image.new("RGB", (30, 20)).save(root / f"images/train/nested/{i}.png")
        (root / f"labels/train/nested/{i}.txt").write_text("2 0.5 0.5 0.8 0.8\n")
    (root / "model").mkdir()
    (root / "model/sam2.1_s.pt").touch()
    cfg = root / "models.json"
    cfg.write_text(
        json.dumps(
            {
                "default_model": model,
                "models": [{"id": model, "name": "Test", "backend": "sam2", "source": "model"}],
            }
        )
    )
    return ModelRegistry(cfg)


@pytest.mark.parametrize("grouped", [False, True])
def test_headless_converts_yolo_keeps_classes_and_resumes(tmp_path, grouped):
    registry = dataset(tmp_path, count=4)
    if grouped:
        raw = json.loads(registry.path.read_text())
        registry.path.write_text(json.dumps({"segmentation": raw}))
        registry.reload()
    first = segment_dataset(
        tmp_path,
        "",
        registry,
        ExecutionOptions("cpu", "auto", "2"),
        executor_factory=executor,
        available={"cuda": 0, "mps": False},
    )
    assert first["processed"] == first["completed"] == first["total"] == 4
    assert first["failed"] == []
    assert first["plan"]["workers"] == ["cpu", "cpu"]
    label = tmp_path / "labels/train/nested/0.txt"
    assert (tmp_path / "labels_seg/train/nested/0.txt").read_text().startswith("2 ")
    assert label.read_text().startswith("2 ")
    project = Project(tmp_path)
    obj = project.annotation(project.images()[0]["id"]).instances[0]
    assert (
        obj.mask
        and obj.box
        and obj.class_id == next(c for c in project.metadata["classes"] if c["index"] == 2)["id"]
    )
    second = segment_dataset(
        tmp_path, "", registry, executor_factory=executor, available={"cuda": 0, "mps": False}
    )
    assert second["processed"] == second["total"] == 0 and second["skipped"] == 4


def test_headless_reports_failure_and_nonzero_exit(tmp_path, monkeypatch):
    registry = dataset(tmp_path, "fail")
    original = (tmp_path / "labels/train/nested/0.txt").read_text()
    monkeypatch.setattr(
        "annodesk.batch.segment_dataset",
        partial(segment_dataset, executor_factory=executor, available={"cuda": 0, "mps": False}),
    )
    with pytest.raises(SystemExit) as error:
        segment(tmp_path, models_config=registry.path, log_dir=tmp_path / "logs")
    assert error.value.code == 1
    report = json.loads((tmp_path / ".annodesk/segment-report.json").read_text())
    assert report["completed"] == report["total"] == 1
    assert report["failed"][0]["error"] == "Missing local tokenizer"
    assert (tmp_path / "labels/train/nested/0.txt").read_text() == original
    assert not (tmp_path / "labels_seg/train/nested/0.txt").exists()


def test_cli_startup_failure_exit_two_and_report(tmp_path, monkeypatch):
    registry = dataset(tmp_path, "startup-fail")
    monkeypatch.setattr(
        "annodesk.batch.segment_dataset",
        partial(segment_dataset, executor_factory=executor, available={"cuda": 0, "mps": False}),
    )
    with pytest.raises(SystemExit) as error:
        segment(tmp_path, models_config=registry.path, log_dir=tmp_path / "logs")
    assert error.value.code == 2
    report = json.loads((tmp_path / ".annodesk/segment-report.json").read_text())
    assert report["status"] == "failed" and report["completed"] == 0
    assert len(report["remaining"]) == 1


def test_spawn_commit_rejects_concurrent_edits_and_drains_cancel(tmp_path):
    from annodesk.batch import new_report, run_batch
    from annodesk.events import EventLog
    from annodesk.inference import SegmentRequest

    registry = dataset(tmp_path, count=4)
    project = Project(tmp_path)
    request = SegmentRequest(device_type="cpu", num_workers="1")
    report = new_report(project, request)

    def factory(*args):
        instance = executor(*args)
        original = instance.run

        def run(project, images, body, on_result, cancelled, activity):
            edited = False

            def during(workers):
                nonlocal edited
                activity(workers)
                if workers and not edited:
                    edited = True
                    image_id = workers[0]["image"]
                    ann = project.annotation(image_id)
                    ann.notes = "Concurrent human edit"
                    project.save(image_id, ann)
                    report["cancel"] = True

            return original(project, images, body, on_result, cancelled, during)

        instance.run = run
        return instance

    run_batch(
        project,
        registry,
        request,
        report,
        EventLog(),
        lambda: None,
        executor_factory=factory,
        available={"cuda": 0, "mps": False},
    )
    assert report["status"] == "cancelled"
    assert report["completed"] == len(report["failed"]) == 1
    assert len(report["remaining"]) == 3 and report["processed"] == 0
    ann = project.annotation(project.images()[0]["id"])
    assert ann.notes == "Concurrent human edit" and not ann.instances[0].mask


def test_preflight_corruption_counts_failure_not_skip(tmp_path):
    registry = dataset(tmp_path, count=2)
    (tmp_path / "images/train/nested/0.png").write_bytes(b"not an image")
    report = segment_dataset(
        tmp_path, "", registry, executor_factory=executor, available={"cuda": 0, "mps": False}
    )
    assert report["completed"] == report["total"] == 2
    assert len(report["failed"]) == report["processed"] == 1
    assert report["skipped"] == 0


@pytest.mark.skipif(__import__("os").name != "posix", reason="POSIX signal behavior")
def test_spawn_worker_ignores_terminal_sigint(tmp_path):
    import os
    import signal

    from annodesk.devices import resolve_plan
    from annodesk.events import EventLog
    from annodesk.inference import SegmentRequest

    registry = dataset(tmp_path)
    plan = resolve_plan(ExecutionOptions("cpu"), {"cuda": 0, "mps": False})
    pool = executor(registry, "test", plan, EventLog())
    pool.start()
    try:
        worker = next(iter(pool.workers.values())).process
        os.kill(worker.pid, signal.SIGINT)
        worker.join(timeout=0.1)
        assert worker.is_alive()
        results = []
        project = Project(tmp_path)
        pool.run(
            project,
            list(project.entries),
            SegmentRequest(model="test"),
            lambda *args: results.append(args),
        )
        assert len(results) == 1 and results[0][2] is None
    finally:
        pool.close()


def test_crashed_workers_stop_without_counting_uncommitted_images(tmp_path):
    from annodesk.events import EventLog
    from annodesk.execution import StartupError

    registry = dataset(tmp_path, count=3)
    for folder, suffix in [("images", ".png"), ("labels", ".txt")]:
        source = tmp_path / folder / f"train/nested/2{suffix}"
        source.rename(source.with_name("crash" + suffix))
    events = EventLog()
    with pytest.raises(StartupError, match="All workers exited"):
        segment_dataset(
            tmp_path,
            "",
            registry,
            ExecutionOptions("cpu", "auto", "2"),
            events,
            executor_factory=executor,
            available={"cuda": 0, "mps": False},
        )
    report = json.loads((tmp_path / ".annodesk/segment-report.json").read_text())
    assert report["status"] == "failed"
    assert report["processed"] == 2 and report["completed"] == 3
    assert len(report["remaining"]) == 0 and len(report["failed"]) == 1
    assert report["results"][-1]["attempts"] == 2
    assert len([e for e in events.events if e["event_type"] == "worker_crash"]) == 1


def test_dispatch_rechecks_review_and_rejects_replaced_checkpoint(tmp_path):
    from annodesk.devices import DevicePlan
    from annodesk.events import EventLog
    from annodesk.inference import SegmentRequest

    registry = dataset(tmp_path, count=2)
    project = Project(tmp_path)
    ids = list(project.entries)
    pool = executor(registry, "test", DevicePlan("cpu", ["cpu"], ["cpu"]), EventLog())
    pool.start()
    try:
        ann = project.annotation(ids[0])
        ann.segmentation_review = "ok"
        ann.explicit_empty["segmentation"] = True
        project.save(ids[0], ann)
        registry.weights("test").write_bytes(b"replacement checkpoint")
        results = []
        pool.run(project, ids, SegmentRequest(model="test"), lambda *args: results.append(args))
        assert len(results) == 2
        assert "eligibility" in results[0][2]
        assert "checkpoint changed" in results[1][2]
        assert not any(project.annotation(i).instances[0].mask for i in ids)
    finally:
        pool.close()


def test_batch_freezes_configured_directory_for_symlinked_weights(tmp_path):
    registry = dataset(tmp_path)
    target = tmp_path / "all-weights"
    target.mkdir()
    (target / "sam2.1_s.pt").write_bytes(b"checkpoint")
    (target / "sam2.1_l.pt").write_bytes(b"other")
    (tmp_path / "model/sam2.1_s.pt").unlink()
    (tmp_path / "model/sam2.1_s.pt").symlink_to(target / "sam2.1_s.pt")
    report = segment_dataset(
        tmp_path, "", registry, executor_factory=executor, available={"cuda": 0, "mps": False}
    )
    assert report["status"] == "complete"
    assert report["frozen_config"]["models"][0]["source"] == str(tmp_path / "model")


def test_spawn_configuration_keeps_symlink_directory(tmp_path):
    from annodesk.devices import DevicePlan
    from annodesk.events import EventLog
    from annodesk.execution import ImageExecutor

    registry = dataset(tmp_path)
    target = tmp_path / "other"
    target.mkdir()
    (target / "sam2.1_s.pt").touch()
    (tmp_path / "model/sam2.1_s.pt").unlink()
    (tmp_path / "model/sam2.1_s.pt").symlink_to(target / "sam2.1_s.pt")
    pool = ImageExecutor(registry, "test", DevicePlan("cpu", ["cpu"], ["cpu"]), EventLog())
    try:
        assert pool.config["models"][0]["source"] == str(tmp_path / "model")
    finally:
        pool.close()
