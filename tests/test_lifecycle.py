import json

from PIL import Image

from annodesk.domain import Instance
from annodesk.lifecycle import export_project, reindex_classes, restore_trash, trash_excluded
from annodesk.storage import Project


def make_project(tmp_path):
    (tmp_path / "images/train").mkdir(parents=True)
    Image.new("RGB", (100, 80)).save(tmp_path / "images/train/a.png")
    project = Project(tmp_path)
    category = project.add_category("Car")
    image_id = project.images()[0]["id"]
    ann = project.annotation(image_id)
    ann.instances = [Instance(class_id=category["id"], box=[10, 20, 70, 60])]
    project.save(image_id, ann)
    return project, image_id


def test_reindex_preserves_uuid_and_changes_txt(tmp_path):
    project, image_id = make_project(tmp_path)
    project.add_category("Person")
    ids = [c["id"] for c in project.metadata["classes"]]
    reindex_classes(project, list(reversed(ids)))
    assert project.annotation(image_id).instances[0].class_id == ids[0]
    assert project.label_path(image_id).read_text().startswith("1 ")
    project.save(image_id, project.annotation(image_id))


def test_export_and_recoverable_exclusion(tmp_path):
    project, image_id = make_project(tmp_path)
    ann = project.annotation(image_id)
    ann.detection_review = "ok"
    project.save(image_id, ann)
    output = export_project(project, "detection")
    assert (output / "labels/train/a.txt").read_text().startswith("0 ")
    report = json.loads((output / "report.json").read_text())
    assert report["exported"] == 1
    ann = project.annotation(image_id)
    ann.excluded = True
    project.save(image_id, ann)
    operation = trash_excluded(project)
    assert not (tmp_path / "images/train/a.png").exists()
    restore_trash(project, operation)
    assert (tmp_path / "images/train/a.png").exists()
    assert Project(tmp_path).annotation(image_id).excluded


def test_reindex_refuses_external_label_changes(tmp_path):
    import pytest

    from annodesk.storage import RevisionConflict

    project, image_id = make_project(tmp_path)
    project.label_path(image_id).write_text("0 0.8 0.8 0.2 0.2\n")
    with pytest.raises(RevisionConflict):
        reindex_classes(project)


def test_export_projects_legacy_rle_only_records(tmp_path):
    import numpy as np

    from annodesk.masks import encode_mask

    project, image_id = make_project(tmp_path)
    # Simulate a valid existing record written without a polygon projection.
    record = json.loads(project.annotation_path(image_id).read_text())
    record["instances"][0]["box"] = None
    record["instances"][0]["mask"] = encode_mask(np.ones((80, 100), dtype=np.uint8))
    record["instances"][0]["polygons"] = []
    record["segmentation_review"] = "ok"
    project.annotation_path(image_id).write_text(json.dumps(record))
    output = export_project(project, "segmentation", "yolo")
    assert (output / "labels/train/a.txt").read_text().strip()
    assert json.loads((output / "report.json").read_text())["exported"] == 1


def test_empty_mask_does_not_export_as_unconfirmed_background(tmp_path):
    import numpy as np

    from annodesk.masks import encode_mask

    project, image_id = make_project(tmp_path)
    ann = project.annotation(image_id)
    ann.instances[0].mask = encode_mask(np.zeros((80, 100), dtype=np.uint8))
    ann.segmentation_review = "ok"
    # Simulate an older persisted record; new approvals reject empty masks.
    project.annotation_path(image_id).write_text(json.dumps(ann.model_dump()))
    import pytest

    with pytest.raises(ValueError, match="No images qualify"):
        export_project(project, "segmentation")
    assert not (project.private / "exports").exists()
    ann = project.annotation(image_id)
    ann.explicit_empty["segmentation"] = True
    project.save(image_id, ann)
    output = export_project(project, "segmentation")
    assert json.loads((output / "report.json").read_text())["exported"] == 1
    assert (output / "labels/train/a.txt").read_text() == ""


def test_export_cancellation_during_packaging_removes_only_incomplete_output(tmp_path):
    import pytest

    project, image_id = make_project(tmp_path)
    ann = project.annotation(image_id)
    ann.detection_review = "ok"
    project.save(image_id, ann)
    previous = export_project(project, "detection")
    cancel = False

    def progress(_completed, _total, phase="running"):
        nonlocal cancel
        if phase == "packaging":
            cancel = True

    with pytest.raises(ValueError, match="Export cancelled"):
        export_project(
            project,
            "detection",
            progress=progress,
            cancelled=lambda: cancel,
            output=str(project.private / "exports" / "cancelled"),
        )
    assert list((project.private / "exports").iterdir()) == [previous]
    assert (previous / "report.json").exists()


def test_cancel_during_metadata_write_stops_remaining_packaging(tmp_path, monkeypatch):
    import pytest

    from annodesk import lifecycle

    project, image_id = make_project(tmp_path)
    ann = project.annotation(image_id)
    ann.detection_review = "ok"
    project.save(image_id, ann)
    previous = export_project(project, "detection")
    cancel = False
    writes = []
    original = lifecycle.atomic_write

    def write_then_cancel(path, text):
        nonlocal cancel
        original(path, text)
        writes.append(path.name)
        if path.name == "data.yaml":
            cancel = True

    monkeypatch.setattr(lifecycle, "atomic_write", write_then_cancel)
    with pytest.raises(ValueError, match="Export cancelled"):
        export_project(project, "detection", format="coco", cancelled=lambda: cancel)
    assert "class-id-map.json" not in writes
    assert "annotations.json" not in writes
    assert list((project.private / "exports").iterdir()) == [previous]


def test_restore_rebuilds_projections_after_class_reindex(tmp_path):
    import numpy as np

    from annodesk.masks import encode_mask

    project, image_id = make_project(tmp_path)
    original_class = project.metadata["classes"][0]["id"]
    project.add_category("Person")
    ann = project.annotation(image_id)
    mask = np.zeros((80, 100), dtype=np.uint8)
    mask[20:60, 10:70] = 1
    ann.instances[0].mask = encode_mask(mask)
    ann.excluded = True
    project.save(image_id, ann)
    operation = trash_excluded(project)
    reindex_classes(project, [c["id"] for c in reversed(project.metadata["classes"])])
    restore_trash(project, operation)
    restored = project.annotation(image_id)
    assert restored.instances[0].class_id == original_class
    assert restored.excluded
    assert restored.instances[0].mask == ann.instances[0].mask
    for seg in (False, True):
        assert project.label_path(image_id, seg).read_text().startswith("1 ")
    project.validate_fingerprints(image_id)
    project.save(image_id, restored)
    reopened = Project(tmp_path)
    reopened.validate_fingerprints(image_id)


def test_restore_does_not_recreate_deleted_classes_or_move_files(tmp_path):
    import pytest

    project, image_id = make_project(tmp_path)
    ann = project.annotation(image_id)
    ann.excluded = True
    project.save(image_id, ann)
    operation = trash_excluded(project)
    project.metadata["classes"] = []
    project.write_metadata()
    with pytest.raises(ValueError, match="deleted classes"):
        restore_trash(project, operation)
    assert not (tmp_path / "images/train/a.png").exists()
    assert project.entries == {}
    manifest = json.loads((project.private / "trash" / operation / "manifest.json").read_text())
    assert not manifest.get("restored")
    assert project.metadata["classes"] == []


def test_pending_detection_export_rejects_invalid_source_box(tmp_path):
    import pytest

    (tmp_path / "images").mkdir()
    Image.new("RGB", (100, 80)).save(tmp_path / "images/a.png")
    (tmp_path / "labels").mkdir()
    label = tmp_path / "labels/a.txt"
    label.write_text("0 0.1 0.5 0.8 0.5\n")
    project = Project(tmp_path)
    image_id = project.images()[0]["id"]
    with pytest.raises(ValueError) as error:
        export_project(project, "detection", include_pending=True)
    assert f"{label}:1: Box outside image" in str(error.value)
    assert not project.annotation_path(image_id).exists()
    assert not list((project.private / "exports").rglob("*.txt"))


def test_detection_export_rejects_legacy_materialized_invalid_box(tmp_path):
    import pytest

    project, image_id = make_project(tmp_path)
    path = project.annotation_path(image_id)
    record = json.loads(path.read_text())
    record["instances"][0]["box"] = [-30, 20, 50, 60]
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="Box outside image") as error:
        export_project(project, "detection", include_pending=True)
    assert str(path) in str(error.value)
    assert not list((project.private / "exports").rglob("*.txt"))
    # Export validation does not silently modify authoritative records or source labels.
    assert json.loads(path.read_text()) == record
