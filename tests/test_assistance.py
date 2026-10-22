import json

import numpy as np
import pytest
import yaml
from fastapi.testclient import TestClient
from PIL import Image

from annodesk.app import create_app
from annodesk.batch import segment_dataset
from annodesk.classes import compatible, read_classes
from annodesk.domain import Instance
from annodesk.inference import SegmentRequest, compute_annotation
from annodesk.masks import encode_mask
from annodesk.models import ModelRegistry
from annodesk.operations import commit_result, prepare_detection, preview
from annodesk.storage import Project, RevisionConflict
from tests.fakes import executor

NAMES = {0: "cat", 1: "dog", 2: "bird"}


def fixture(root, count=1):
    (root / "images").mkdir()
    for i in range(count):
        Image.new("RGB", (30, 20)).save(root / f"images/{i}.png")
    (root / "model").mkdir()
    (root / "model/best.pt").touch()
    (root / "classes.yaml").write_text(yaml.safe_dump({"names": NAMES}))
    path = root / "models.json"
    path.write_text(
        json.dumps(
            {
                "default_detection_model": "det",
                "models": [
                    {
                        "id": "det",
                        "name": "Detector",
                        "backend": "ultralytics",
                        "source": "model",
                        "classes_file": "classes.yaml",
                    }
                ],
            }
        )
    )
    return Project(root), ModelRegistry(path)


def metadata(names):
    return {"classes": [{"index": i, "name": name, "id": str(i)} for i, name in names.items()]}


@pytest.mark.parametrize(
    "names",
    [NAMES, {0: "cat"}, {0: "cat", 2: "bird"}, {0: "cat", 1: "dog", 2: "bird", 3: "horse"}, {}],
)
def test_strict_subsets(names):
    assert compatible(NAMES, metadata(names))["relation"] in {
        "equal",
        "model_subset",
        "project_subset",
    }


@pytest.mark.parametrize("names", [{0: "dog"}, {3: "cat"}, {0: "cat", 3: "horse"}, {0: "Cat"}])
def test_strict_mismatches(names):
    with pytest.raises(ValueError, match="Incompatible"):
        compatible(NAMES, metadata(names))


def test_class_files_relative_to_json_without_hf_fallback(tmp_path, monkeypatch):
    _, registry = fixture(tmp_path)
    assert registry.entry("", "detection").id == "det"
    assert registry.config.default_model == ""
    assert read_classes(registry.classes_path("det")) == NAMES
    registry.classes_path("det").unlink()
    remote = tmp_path / "hf"
    remote.mkdir()
    (remote / "classes.yaml").write_text("names: [cat, dog, bird]")
    monkeypatch.setenv("HF_MODELS", str(remote))
    with pytest.raises(ValueError, match="Cannot read"):
        read_classes(registry.classes_path("det"))


class Detector:
    def detect(self, *_):
        return [{"box": [1.0, 2.0, 9.0, 10.0], "class_index": 2, "confidence": 0.9}]


def test_lazy_classes_atomic_save_and_sparse_reopen(tmp_path):
    project, _ = fixture(tmp_path)
    project.add_category("cat")
    image_id = next(iter(project.entries))
    request = prepare_detection(
        project, SegmentRequest(operation="detection", model="det", allow_new_classes=True), NAMES
    )
    ann = compute_annotation(
        project.image_path(image_id), (30, 20), project.annotation(image_id), request, Detector()
    )
    assert [c["index"] for c in project.metadata["classes"]] == [0]
    saved = commit_result(project, image_id, ann, request)
    assert saved.instances[0].confidence == 0.9
    assert saved.instances[0].class_id == project.metadata["classes"][1]["id"]
    assert [c["index"] for c in project.metadata["classes"]] == [0, 2]
    assert project.label_path(image_id).read_text().startswith("2 ")
    assert yaml.safe_load((tmp_path / "data.yaml").read_text())["names"] == {0: "cat", 2: "bird"}
    assert [c["index"] for c in Project(tmp_path).metadata["classes"]] == [0, 2]
    assert "operation_stats" not in json.loads(project.annotation_path(image_id).read_text())


def test_save_conflict_does_not_create_class(tmp_path):
    project, _ = fixture(tmp_path)
    project.add_category("cat")
    image_id = next(iter(project.entries))
    request = prepare_detection(
        project, SegmentRequest(operation="detection", model="det", allow_new_classes=True), NAMES
    )
    computed = compute_annotation(
        project.image_path(image_id), (30, 20), project.annotation(image_id), request, Detector()
    )
    edited = project.annotation(image_id)
    edited.notes = "human edit"
    project.save(image_id, edited)
    with pytest.raises(RevisionConflict):
        commit_result(project, image_id, computed, request)
    assert [c["index"] for c in project.metadata["classes"]] == [0]
    assert project.annotation(image_id).notes == "human edit"


def test_disabled_extra_classes_are_discarded_without_approving_empty(tmp_path):
    project, _ = fixture(tmp_path)
    project.add_category("cat")
    image_id = next(iter(project.entries))
    body = prepare_detection(project, SegmentRequest(operation="detection", model="det"), NAMES)
    ann = project.annotation(image_id)
    ann.detection_review = "ok"
    result = compute_annotation(project.image_path(image_id), (30, 20), ann, body, Detector())
    assert result.operation_stats["detections_discarded"] == 1
    assert not result.instances and result.detection_review == "ok"
    assert not result.explicit_empty.get("detection")


def test_mask_box_single_pixel_keeps_instance_mask_and_segmentation_review(tmp_path):
    project, _ = fixture(tmp_path)
    category = project.add_category("cat")
    image_id = next(iter(project.entries))
    ann = project.annotation(image_id)
    binary = np.zeros((20, 30), dtype=np.uint8)
    binary[19, 29] = 1
    obj = Instance(class_id=category["id"], mask=encode_mask(binary))
    ann.instances = [obj]
    ann.detection_review = ann.segmentation_review = "ok"
    result = compute_annotation(
        project.image_path(image_id),
        (30, 20),
        ann,
        SegmentRequest(operation="boxes_from_masks"),
        None,
    )
    assert result.instances[0].box == [29, 19, 30, 20]
    assert result.instances[0].id == obj.id and result.instances[0].mask == obj.mask
    assert result.detection_review == "pending" and result.segmentation_review == "ok"
    obj.locked = True
    obj.box = [0, 0, 2, 2]
    compute_annotation(
        project.image_path(image_id),
        (30, 20),
        ann,
        SegmentRequest(operation="boxes_from_masks", recalculate_boxes=True),
        None,
    )
    assert obj.box == [0, 0, 2, 2]


def test_preview_is_read_only_and_uses_target_review_state(tmp_path):
    project, _ = fixture(tmp_path)
    assert preview(project, SegmentRequest(operation="detection"))["counts"]["eligible"] == 1
    assert not list((project.private / "annotations").glob("*.json"))
    image_id = next(iter(project.entries))
    ann = project.annotation(image_id)
    ann.segmentation_review = "ok"
    ann.instances = [Instance(polygons=[[[1, 1], [9, 1], [9, 9]]])]
    project.save(image_id, ann)
    assert preview(project, SegmentRequest(operation="boxes_from_masks"))["counts"]["eligible"] == 1
    ann = project.annotation(image_id)
    ann.detection_review = "uncertain"
    project.save(image_id, ann)
    assert (
        preview(project, SegmentRequest(operation="boxes_from_masks"))["counts"]["review_state"]
        == 1
    )
    assert (
        preview(project, SegmentRequest(operation="boxes_from_masks", review_states=["uncertain"]))[
            "total"
        ]
        == 1
    )


def test_geometry_batch_does_not_probe_or_load_a_model(tmp_path, monkeypatch):
    project, registry = fixture(tmp_path)
    image_id = next(iter(project.entries))
    ann = project.annotation(image_id)
    ann.instances = [Instance(polygons=[[[2, 3], [8, 3], [8, 9]]])]
    project.save(image_id, ann)
    (tmp_path / "model/best.pt").unlink()
    monkeypatch.setattr(
        "annodesk.batch.resolve_plan", lambda *_: pytest.fail("Geometry must not probe Torch")
    )
    report = segment_dataset(
        tmp_path, "", registry, request=SegmentRequest(operation="boxes_from_masks")
    )
    assert report["processed"] == report["boxes_added"] == 1
    assert Project(tmp_path).annotation(image_id).instances[0].box == [2, 3, 8, 9]


def test_spawn_detection_uses_parent_class_creation(tmp_path):
    project, registry = fixture(tmp_path, count=3)
    body = SegmentRequest(
        operation="detection", model="det", allow_new_classes=True, device_type="cpu", num_workers=2
    )
    report = segment_dataset(
        tmp_path,
        "det",
        registry,
        request=body,
        executor_factory=executor,
        class_probe=lambda *_: NAMES,
        available={"cuda": 0, "mps": False},
    )
    assert report["processed"] == 3
    assert report["boxes_added"] == 3
    reopened = Project(tmp_path)
    assert len(reopened.metadata["classes"]) == 1
    assert reopened.metadata["classes"][0]["index"] == 2
    uuids = {reopened.annotation(i).instances[0].class_id for i in reopened.entries}
    assert len(uuids) == 1


def test_model_settings_and_current_geometry_http(tmp_path):
    project, registry = fixture(tmp_path)
    image_id = next(iter(project.entries))
    ann = project.annotation(image_id)
    ann.instances = [Instance(polygons=[[[1, 1], [5, 1], [5, 6]]])]
    project.save(image_id, ann)
    with TestClient(create_app(project=tmp_path, models_config=registry.path)) as client:
        config = client.post(
            "/api/v1/model-settings",
            json={"operation": "detection", "model": "det", "allow_new_classes": True},
        )
        assert config.status_code == 200
        assert config.json()["active_models"]["detection"] == "det"
        result = client.post(f"/api/v1/images/{image_id}/boxes-from-masks", json={})
        assert result.status_code == 200, result.text
        assert result.json()["instances"][0]["box"] == [1, 1, 5, 6]
        assert (
            client.post(
                "/api/v1/jobs/preview", json={"operation": "detection", "image_ids": ["missing"]}
            ).status_code
            == 400
        )


def test_sam_changed_mask_resets_needs_review(tmp_path):
    project, _ = fixture(tmp_path)
    image_id = next(iter(project.entries))
    ann = project.annotation(image_id)
    ann.instances = [Instance(box=[1, 1, 8, 8])]
    ann.segmentation_review = "uncertain"

    class Sam:
        def predict(self, *_):
            return [np.ones((20, 30), dtype=np.uint8)]

    result = compute_annotation(
        project.image_path(image_id), (30, 20), ann, SegmentRequest(), Sam()
    )
    assert result.instances[0].mask
    assert result.segmentation_review == "pending"


def test_sparse_ids_export_to_continuous_copy(tmp_path):
    from annodesk.lifecycle import export_project

    project, _ = fixture(tmp_path)
    image_id = next(iter(project.entries))
    body = prepare_detection(
        project, SegmentRequest(operation="detection", model="det", allow_new_classes=True), NAMES
    )
    result = compute_annotation(
        project.image_path(image_id), (30, 20), project.annotation(image_id), body, Detector()
    )
    saved = commit_result(project, image_id, result, body)
    saved.detection_review = "ok"
    project.save(image_id, saved)
    output = export_project(project, "detection", "yolo")
    assert json.loads((output / "class-id-map.json").read_text()) == {"2": 0}
    assert (output / "labels/0.txt").read_text().startswith("0 ")
    assert project.metadata["classes"][0]["index"] == 2


def test_resume_rejects_changed_project_class_snapshot(tmp_path):
    from annodesk.batch import new_report, run_batch
    from annodesk.events import EventLog

    project, registry = fixture(tmp_path)
    body = SegmentRequest(operation="detection", model="det", allow_new_classes=True)
    report = new_report(project, body)
    run_batch(
        project,
        registry,
        body,
        report,
        EventLog(),
        lambda: report.update(cancel=True),
        class_probe=lambda *_: NAMES,
        available={"cuda": 0, "mps": False},
    )
    assert report["status"] == "cancelled" and report["project_classes"] == []
    project.add_category("cat")
    report["cancel"] = False
    with pytest.raises(ValueError, match="Project class definitions changed"):
        run_batch(project, registry, body, report, EventLog(), lambda: None)
    assert not project.annotation(next(iter(project.entries))).instances
