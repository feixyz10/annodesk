from pathlib import Path

import pytest
from PIL import Image

from annodesk.domain import Annotation, Instance
from annodesk.storage import Project, RevisionConflict


def dataset(tmp_path: Path):
    images = tmp_path / "images" / "train" / "camera"
    images.mkdir(parents=True)
    Image.new("RGB", (100, 80)).save(images / "a.png")
    labels = tmp_path / "labels" / "train" / "camera"
    labels.mkdir(parents=True)
    (labels / "a.txt").write_text("2 0.5 0.5 0.4 0.5\n")
    return tmp_path


def test_import_save_and_clear(tmp_path):
    project = Project(dataset(tmp_path))
    item = project.images()[0]
    ann = project.annotation(item["id"])
    assert ann.instances[0].box == [30, 20, 70, 60]
    assert project.metadata["classes"][2]["name"] == "class_2"
    saved = project.save(item["id"], ann)
    assert saved.revision == 1
    with pytest.raises(RevisionConflict):
        project.save(item["id"], ann)
    saved.instances = []
    project.save(item["id"], saved)
    assert (tmp_path / "labels/train/camera/a.txt").read_text() == ""
    assert Project(tmp_path).annotation(item["id"]).instances == []


def test_mask_only_does_not_create_box(tmp_path):
    project = Project(dataset(tmp_path))
    item = project.images()[0]
    ann = project.annotation(item["id"])
    ann.instances = [
        Instance(class_id=ann.instances[0].class_id, polygons=[[[1, 1], [8, 1], [8, 8]]])
    ]
    project.save(item["id"], ann)
    assert (tmp_path / "labels/train/camera/a.txt").read_text() == ""
    assert (tmp_path / "labels_seg/train/camera/a.txt").read_text().startswith("2 ")


def test_duplicate_stem_rejected(tmp_path):
    root = dataset(tmp_path)
    Image.new("RGB", (100, 80)).save(root / "images/train/camera/a.jpg")
    with pytest.raises(ValueError, match="same label"):
        Project(root)


def test_invalid_geometry_rejected(tmp_path):
    project = Project(dataset(tmp_path))
    ann = Annotation(instances=[Instance(class_id="missing", box=[0, 0, 20, 10])])
    with pytest.raises(ValueError, match="class"):
        project.save(project.images()[0]["id"], ann)
    with pytest.raises(ValueError):
        Instance(class_id="x", box=[float("nan"), 0, 20, 10])


def test_mismatched_mask_dimensions_rejected(tmp_path):
    import numpy as np

    from annodesk.masks import encode_mask

    project = Project(dataset(tmp_path))
    image_id = project.images()[0]["id"]
    ann = project.annotation(image_id)
    ann.instances[0].mask = encode_mask(np.ones((2, 2), dtype=np.uint8))
    with pytest.raises(ValueError, match="mask"):
        project.save(image_id, ann)
