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
