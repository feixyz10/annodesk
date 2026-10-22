from fastapi.testclient import TestClient
from PIL import Image

from annodesk.app import create_app


def test_stale_browser_cannot_read_or_modify_a_different_project(tmp_path):
    import shutil

    from annodesk.storage import Project

    first, second = tmp_path / "first", tmp_path / "second"
    (first / "images").mkdir(parents=True)
    Image.new("RGB", (10, 10)).save(first / "images/a.png")
    Project(first)
    # A copied dataset keeps its persistent project UUID but needs a new runtime session.
    shutil.copytree(first, second)
    with TestClient(create_app(project=first)) as client:
        old = client.get("/api/v1/project").json()
        image_id = client.get("/api/v1/images").json()["items"][0]["id"]
        annotation = client.get(f"/api/v1/images/{image_id}/annotation").json()
        new = client.post("/api/v1/project/open", json={"path": str(second)}).json()
        assert old["id"] == new["id"] and old["session"] != new["session"]
        headers = {"X-AnnoDesk-Project": old["session"]}
        calls = [
            ("PUT", f"/images/{image_id}/annotation", {**annotation, "notes": "wrong project"}),
            ("POST", "/classes", {"name": "wrong project"}),
            ("POST", "/tags", {"name": "wrong project"}),
            ("POST", "/jobs", {}),
            ("POST", "/export", {}),
            ("POST", "/trash/excluded", {}),
            ("GET", "/images", None),
            ("GET", f"/images/{image_id}/annotation", None),
        ]
        for method, path, body in calls:
            response = client.request(method, "/api/v1" + path, headers=headers, json=body)
            assert response.status_code == 409, (path, response.text)
        for resource in ("file", "thumbnail"):
            assert (
                client.get(
                    f"/api/v1/images/{image_id}/{resource}?project_session={old['session']}"
                ).status_code
                == 409
            )
            assert (
                client.get(
                    f"/api/v1/images/{image_id}/{resource}?project_session={new['session']}"
                ).status_code
                == 200
            )
        assert client.get("/api/v1/project", headers=headers).json()["session"] == new["session"]
        assert client.get(f"/api/v1/images/{image_id}/annotation").json()["notes"] == ""
        assert client.get("/api/v1/project").json()["classes"] == []


def test_project_switch_waits_for_inflight_annotation_write(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from annodesk.storage import Project

    first, second = tmp_path / "first", tmp_path / "second"
    for root in (first, second):
        (root / "images").mkdir(parents=True)
        Image.new("RGB", (10, 10)).save(root / "images/a.png")
    entered, release = Event(), Event()
    original = Project.save

    def blocked_save(self, *args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(self, *args, **kwargs)

    with TestClient(create_app(project=first)) as client:
        image_id = client.get("/api/v1/images").json()["items"][0]["id"]
        annotation = client.get(f"/api/v1/images/{image_id}/annotation").json()
        monkeypatch.setattr(Project, "save", blocked_save)
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                client.put, f"/api/v1/images/{image_id}/annotation", json=annotation
            )
            try:
                assert entered.wait(5)
                response = client.post("/api/v1/project/open", json={"path": str(second)})
                assert response.status_code == 409
                assert client.get("/api/v1/project").json()["root"] == str(first.resolve())
            finally:
                release.set()
            assert future.result(timeout=5).status_code == 200
        assert client.post("/api/v1/project/open", json={"path": str(second)}).status_code == 200


def test_category_updates_reject_invalid_names_without_mutating_project(tmp_path):
    (tmp_path / "images").mkdir()
    with TestClient(create_app(project=tmp_path)) as client:
        cat = client.post("/api/v1/classes", json={"name": "cat"}).json()
        client.post("/api/v1/classes", json={"name": "dog"})
        url = f"/api/v1/categories/{cat['id']}"
        for name in ("   ", "dog"):
            assert client.patch(url, json={"name": name}).status_code == 400
            assert client.get("/api/v1/project").json()["classes"][0] == cat
        # Tag and class palettes are independent.
        tag = client.post("/api/v1/tags", json={"name": "night"}).json()
        assert (
            client.patch(f"/api/v1/categories/{tag['id']}", json={"name": "cat"}).status_code == 200
        )


def test_category_write_failure_rolls_back_memory(tmp_path, monkeypatch):
    from annodesk.storage import Project

    (tmp_path / "images").mkdir()
    app = create_app(project=tmp_path)
    with TestClient(app, raise_server_exceptions=False) as client:
        cat = client.post("/api/v1/classes", json={"name": "cat"}).json()

        def fail_write(self):
            raise OSError("disk unavailable")

        monkeypatch.setattr(Project, "write_metadata", fail_write)
        assert (
            client.patch(f"/api/v1/categories/{cat['id']}", json={"name": "bird"}).status_code
            == 500
        )
        assert client.post("/api/v1/classes", json={"name": "dog"}).status_code == 500
        assert client.get("/api/v1/project").json()["classes"] == [cat]


def test_project_annotation_http_roundtrip(tmp_path):
    (tmp_path / "images/nested").mkdir(parents=True)
    Image.new("RGB", (120, 80)).save(tmp_path / "images/nested/a.png")
    client = TestClient(create_app())
    response = client.post("/api/v1/project/open", json={"path": str(tmp_path)})
    assert response.status_code == 200
    category = client.post("/api/v1/classes", json={"name": "Car"}).json()
    images = client.get("/api/v1/images").json()["items"]
    image_id = images[0]["id"]
    ann = client.get(f"/api/v1/images/{image_id}/annotation").json()
    ann["instances"] = [{"class_id": category["id"], "box": [10, 10, 90, 60]}]
    response = client.put(f"/api/v1/images/{image_id}/annotation", json=ann)
    assert response.status_code == 200, response.text
    assert response.json()["revision"] == 1
    assert client.put(f"/api/v1/images/{image_id}/annotation", json=ann).status_code == 409
    assert (
        client.get(f"/api/v1/images/{image_id}/thumbnail").headers["content-type"] == "image/jpeg"
    )
    assert client.get(f"/api/v1/images/{image_id}/file").status_code == 200
    assert client.get("/api/v1/images/missing/file").status_code == 404


def test_reopening_project_rebinds_model_service(tmp_path, monkeypatch):
    import numpy as np

    from annodesk.inference import UltralyticsAdapter

    (tmp_path / "images").mkdir()
    Image.new("RGB", (30, 20)).save(tmp_path / "images/a.png")
    monkeypatch.setattr(
        UltralyticsAdapter, "predict", lambda *_: [np.ones((20, 30), dtype=np.uint8)]
    )
    client = TestClient(create_app())
    client.post("/api/v1/project/open", json={"path": str(tmp_path)})
    client.get("/api/v1/jobs")  # allocate the old project-bound service
    client.post("/api/v1/project/open", json={"path": str(tmp_path)})
    category = client.post("/api/v1/classes", json={"name": "New"}).json()
    image_id = client.get("/api/v1/images").json()["items"][0]["id"]
    ann = client.get(f"/api/v1/images/{image_id}/annotation").json()
    ann["instances"] = [{"id": "target", "class_id": category["id"], "box": [1, 1, 28, 18]}]
    client.put(f"/api/v1/images/{image_id}/annotation", json=ann)
    response = client.post(f"/api/v1/images/{image_id}/segment", json={"instance_id": "target"})
    assert response.status_code == 200, response.text


def test_project_switch_holds_old_lease_and_rejects_writes_until_ready(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    import pytest

    from annodesk import routes
    from annodesk.lease import ProjectLease

    first, second = tmp_path / "first", tmp_path / "second"
    for root in (first, second):
        (root / "images").mkdir(parents=True)
        Image.new("RGB", (10, 10)).save(root / "images/a.png")
    entered, release = Event(), Event()
    original = routes.Project

    def preparing_project(root):
        if root.resolve() == second.resolve():
            entered.set()
            assert release.wait(5)
        return original(root)

    with TestClient(create_app(project=first)) as client:
        session = client.get("/api/v1/project").json()["session"]
        monkeypatch.setattr(routes, "Project", preparing_project)
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                client.post, "/api/v1/project/open", json={"path": str(second)}
            )
            try:
                assert entered.wait(5)
                with pytest.raises(ValueError, match="in use"):
                    ProjectLease(first)
                response = client.post(
                    "/api/v1/classes",
                    json={"name": "late"},
                    headers={"X-AnnoDesk-Project": session},
                )
                assert response.status_code == 409
            finally:
                release.set()
            assert future.result(timeout=5).status_code == 200
        with ProjectLease(first):
            pass
        assert client.get("/api/v1/project").json()["classes"] == []


def test_http_queued_segment_cannot_overwrite_later_human_mask(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    import numpy as np

    from annodesk.domain import Instance
    from annodesk.inference import SegmentationService
    from annodesk.masks import decode_mask, encode_mask
    from annodesk.storage import Project

    (tmp_path / "images").mkdir()
    Image.new("RGB", (30, 20)).save(tmp_path / "images/a.png")
    project = Project(tmp_path)
    category = project.add_category("Object")
    image_id = project.images()[0]["id"]
    ann = project.annotation(image_id)
    obj = Instance(class_id=category["id"], prompt_box=[2, 2, 26, 18])
    ann.instances = [obj]
    project.save(image_id, ann)
    queued, release = Event(), Event()

    class Service(SegmentationService):
        def __init__(self, project, **kwargs):
            # The blocked executor models an earlier in-flight model request.
            super().__init__(project, adapter=object())
            self.executor.submit(release.wait)

        def submit(self, *args):
            future = super().submit(*args)
            queued.set()
            return future

    monkeypatch.setattr("annodesk.routes.SegmentationService", Service)
    with TestClient(create_app(project=tmp_path)) as client, ThreadPoolExecutor() as executor:
        pending = executor.submit(
            client.post, f"/api/v1/images/{image_id}/segment", json={"instance_id": obj.id}
        )
        try:
            assert queued.wait(5)
            annotation_url = f"/api/v1/images/{image_id}/annotation"
            human = client.get(annotation_url).json()
            mask = np.zeros((20, 30), dtype=np.uint8)
            mask[5:7, 6:8] = 1
            human["instances"][0]["mask"] = encode_mask(mask)
            human["segmentation_review"] = "ok"
            saved = client.put(annotation_url, json=human)
            assert saved.status_code == 200, saved.text
        finally:
            release.set()
        response = pending.result(timeout=5)
        assert response.status_code == 409, response.text
        restored = client.get(annotation_url).json()
        assert {key: restored[key] for key in saved.json()} == saved.json()
        assert decode_mask(restored["instances"][0]["mask"]).sum() == 4


def test_trash_and_restore_wait_for_running_or_cancelling_batch(tmp_path, monkeypatch):
    import time
    from threading import Event

    from tests.test_batch import dataset

    registry = dataset(tmp_path, count=2)
    entered, release = Event(), Event()

    def blocked_batch(project, registry, body, job, events, persist, **kwargs):
        entered.set()
        assert release.wait(10)
        job.update(status="cancelled" if job["cancel"] else "complete")
        persist()

    monkeypatch.setattr("annodesk.jobs.run_batch", blocked_batch)
    with TestClient(create_app(project=tmp_path, models_config=registry.path)) as client:
        image_id = client.get("/api/v1/images").json()["items"][0]["id"]
        annotation_url = f"/api/v1/images/{image_id}/annotation"
        ann = client.get(annotation_url).json()
        ann["excluded"] = True
        assert client.put(annotation_url, json=ann).status_code == 200
        operation = client.post("/api/v1/trash/excluded").json()["operation"]
        job = client.post("/api/v1/jobs", json={}).json()
        try:
            assert entered.wait(5)
            for url in ("/api/v1/trash/excluded", f"/api/v1/trash/{operation}/restore"):
                response = client.post(url)
                assert response.status_code == 409, response.text
            assert client.delete(f"/api/v1/jobs/{job['id']}").status_code == 200
            assert client.post(f"/api/v1/trash/{operation}/restore").status_code == 409
        finally:
            release.set()
        deadline = time.monotonic() + 5
        while client.get("/api/v1/jobs").json()[-1]["status"] == "running":
            assert time.monotonic() < deadline
            time.sleep(0.01)
        assert client.post(f"/api/v1/trash/{operation}/restore").status_code == 200
        assert client.get(annotation_url).json()["excluded"]
        assert client.post("/api/v1/trash/excluded").status_code == 200


def test_trash_holds_job_admission_until_moves_finish(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from annodesk.jobs import BatchJobs
    from annodesk.lifecycle import trash_excluded
    from tests.test_batch import dataset

    registry = dataset(tmp_path, count=2)
    moving, release, starting = Event(), Event(), Event()
    original_start = BatchJobs.start

    def blocked_trash(project):
        moving.set()
        assert release.wait(10)
        return trash_excluded(project)

    def attempted_start(self, *args, **kwargs):
        starting.set()
        return original_start(self, *args, **kwargs)

    def finish_batch(project, registry, body, job, events, persist, **kwargs):
        job["status"] = "complete"
        persist()

    monkeypatch.setattr("annodesk.routes.trash_excluded", blocked_trash)
    monkeypatch.setattr(BatchJobs, "start", attempted_start)
    monkeypatch.setattr("annodesk.jobs.run_batch", finish_batch)
    with TestClient(create_app(project=tmp_path, models_config=registry.path)) as client:
        image_id = client.get("/api/v1/images").json()["items"][0]["id"]
        url = f"/api/v1/images/{image_id}/annotation"
        ann = client.get(url).json()
        ann["excluded"] = True
        assert client.put(url, json=ann).status_code == 200
        with ThreadPoolExecutor(max_workers=2) as executor:
            cleanup = executor.submit(client.post, "/api/v1/trash/excluded")
            try:
                assert moving.wait(5)
                launch = executor.submit(client.post, "/api/v1/jobs", json={})
                assert starting.wait(5)
            finally:
                release.set()
            assert cleanup.result(timeout=5).status_code == 200
            response = launch.result(timeout=5)
            assert response.status_code == 200, response.text
            assert response.json()["input_total"] == 1
            assert list(response.json()["image_paths"].values()) == ["train/nested/1.png"]


def test_missing_mask_get_is_read_only_and_preserves_later_human_save(tmp_path):
    from annodesk.domain import Annotation, Instance
    from annodesk.storage import Project
    from tests.test_storage import dataset

    project = Project(dataset(tmp_path))
    image_id = project.images()[0]["id"]
    label = project.label_path(image_id)
    before = label.read_bytes()
    path = project.annotation_path(image_id)
    assert not path.exists()
    with TestClient(create_app(project=tmp_path)) as client:
        url = f"/api/v1/images/{image_id}/masks/missing"
        assert client.get(url).status_code == 404
        assert not path.exists()  # Even a 404 GET used to materialize a stale YOLO snapshot.
        assert label.read_bytes() == before
        human = Annotation(
            notes="Saved after mask lookup",
            instances=[
                Instance(class_id=project.metadata["classes"][0]["id"], box=[10, 10, 50, 50])
            ],
        )
        saved = client.put(f"/api/v1/images/{image_id}/annotation", json=human.model_dump())
        assert saved.status_code == 200 and saved.json()["revision"] == 1
        committed = path.read_bytes()
        assert client.get(url).status_code == 404
        assert path.read_bytes() == committed
        current = client.get(f"/api/v1/images/{image_id}/annotation").json()
        assert current["revision"] == 1 and current["notes"] == human.notes
        assert current["instances"][0]["box"] == [10, 10, 50, 50]
    Project(tmp_path).validate_fingerprints(image_id)
