import numpy as np
import pytest
from PIL import Image
from pycocotools import mask as mask_utils

from annodesk.domain import Instance
from annodesk.inference import SegmentationService, SegmentRequest
from annodesk.storage import Project


class Adapter:
    def predict(self, _path, _model, _box, _points, _text):
        mask = np.zeros((20, 30), dtype=np.uint8)
        mask[4:16, 5:24] = 1
        mask[8:10, 9:11] = 0
        return [mask]


def test_empty_prediction_preserves_previously_saved_mask(tmp_path):
    from annodesk.masks import encode_mask

    (tmp_path / "images").mkdir()
    Image.new("RGB", (30, 20)).save(tmp_path / "images/a.png")
    project = Project(tmp_path)
    category = project.add_category("Object")
    image_id = project.images()[0]["id"]
    ann = project.annotation(image_id)
    obj = Instance(
        class_id=category["id"],
        box=[2, 2, 26, 18],
        mask=encode_mask(np.ones((20, 30), dtype=np.uint8)),
    )
    ann.instances = [obj]
    ann.segmentation_review = "ok"
    project.save(image_id, ann)
    paths = [
        project.annotation_path(image_id),
        project.label_path(image_id),
        project.label_path(image_id, True),
    ]
    before = [p.read_bytes() for p in paths]

    class Empty:
        def predict(self, *_):
            return [np.zeros((20, 30), dtype=np.uint8)]

    service = SegmentationService(project, adapter=Empty())
    try:
        with pytest.raises(ValueError, match="No mask returned"):
            service.process(image_id, SegmentRequest(instance_id=obj.id))
        assert [p.read_bytes() for p in paths] == before
    finally:
        service.close()


def test_empty_predictions_before_valid_mask_preserve_instance_identity(tmp_path):
    (tmp_path / "images").mkdir()
    Image.new("RGB", (30, 20)).save(tmp_path / "images/a.png")
    project = Project(tmp_path)
    category = project.add_category("Object")
    image_id = project.images()[0]["id"]
    ann = project.annotation(image_id)
    obj = Instance(class_id=category["id"], box=[2, 2, 26, 18])
    ann.instances = [obj]
    ann.explicit_empty["segmentation"] = True
    project.save(image_id, ann)

    class Mixed:
        def predict(self, *_):
            return [np.zeros((20, 30), dtype=np.uint8), np.ones((20, 30), dtype=np.uint8)]

    service = SegmentationService(project, adapter=Mixed())
    try:
        saved = service.process(image_id, SegmentRequest(instance_id=obj.id))
        assert saved.instances[0].id == obj.id
        assert saved.instances[0].class_id == category["id"]
        assert saved.instances[0].box == obj.box
        assert saved.instances[0].polygons
        assert not saved.explicit_empty["segmentation"]
    finally:
        service.close()


def test_real_mask_storage_and_mask_only_semantics(tmp_path):
    (tmp_path / "images").mkdir()
    Image.new("RGB", (30, 20)).save(tmp_path / "images/a.png")
    project = Project(tmp_path)
    category = project.add_category("Object")
    image_id = project.images()[0]["id"]
    ann = project.annotation(image_id)
    obj = Instance(class_id=category["id"], prompt_box=[2, 2, 26, 18])
    ann.instances = [obj]
    project.save(image_id, ann)
    service = SegmentationService(project, adapter=Adapter())
    result = service.process(image_id, SegmentRequest(instance_id=obj.id))
    assert result.instances[0].box is None
    assert result.instances[0].id == obj.id
    encoded = result.instances[0].mask
    encoded["counts"] = encoded["counts"].encode()
    decoded = mask_utils.decode(encoded)
    assert decoded[5, 6] and not decoded[8, 9]
    assert (tmp_path / "labels/a.txt").read_text() == ""
    assert (tmp_path / "labels_seg/a.txt").read_text()
    service.close()


def test_no_prompt_does_not_segment_everything(tmp_path):
    (tmp_path / "images").mkdir()
    Image.new("RGB", (30, 20)).save(tmp_path / "images/a.png")
    project = Project(tmp_path)
    service = SegmentationService(project, adapter=Adapter())
    with pytest.raises(ValueError, match="prompt"):
        service.process(project.images()[0]["id"], SegmentRequest())
    service.close()


@pytest.mark.parametrize("prompt", ["box", "point"])
def test_segment_current_includes_prompt_only_objects(tmp_path, prompt):
    from annodesk.domain import Point

    (tmp_path / "images").mkdir()
    Image.new("RGB", (30, 20)).save(tmp_path / "images/a.png")
    project = Project(tmp_path)
    category = project.add_category("Object")
    image_id = project.images()[0]["id"]
    ann = project.annotation(image_id)
    obj = Instance(
        class_id=category["id"],
        prompt_box=[2, 2, 26, 18] if prompt == "box" else None,
        points=[Point(x=10, y=10)] if prompt == "point" else [],
    )
    ann.instances = [obj]
    project.save(image_id, ann)
    service = SegmentationService(project, adapter=Adapter())
    try:
        result = service.process(image_id, SegmentRequest())
        assert result.instances[0].mask
        assert result.instances[0].box is None
        assert (tmp_path / "labels/a.txt").read_text() == ""
    finally:
        service.close()


@pytest.mark.parametrize("change", ["human_mask", "image", "labels"])
def test_queued_request_rejects_changes_since_admission(tmp_path, change):
    from threading import Event
    from unittest.mock import Mock

    from annodesk.masks import decode_mask, encode_mask

    (tmp_path / "images").mkdir()
    Image.new("RGB", (30, 20)).save(tmp_path / "images/a.png")
    project = Project(tmp_path)
    category = project.add_category("Object")
    image_id = project.images()[0]["id"]
    annotation = project.annotation(image_id)
    obj = Instance(class_id=category["id"], prompt_box=[2, 2, 26, 18])
    annotation.instances = [obj]
    project.save(image_id, annotation)
    adapter = Mock(wraps=Adapter())
    service = SegmentationService(project, adapter=adapter)
    release = Event()
    blocker = service.executor.submit(release.wait)
    try:
        pending = service.submit(image_id, SegmentRequest(instance_id=obj.id))
        if change == "human_mask":
            annotation = project.annotation(image_id)
            mask = np.zeros((20, 30), dtype=np.uint8)
            mask[5:7, 6:8] = 1
            annotation.instances[0].mask = encode_mask(mask)
            annotation.segmentation_review = "ok"
            project.save(image_id, annotation)
        elif change == "image":
            Image.new("RGB", (30, 20), "red").save(project.image_path(image_id))
        else:
            project.label_path(image_id).write_text("0 0.5 0.5 0.2 0.2\n")
        before = project.annotation_path(image_id).read_bytes()
        release.set()
        blocker.result(timeout=5)
        with pytest.raises(ValueError, match="changed"):
            pending.result(timeout=5)
        adapter.predict.assert_not_called()
        assert project.annotation_path(image_id).read_bytes() == before
        if change == "human_mask":
            saved = project.annotation(image_id)
            assert decode_mask(saved.instances[0].mask).sum() == 4
            assert saved.segmentation_review == "ok"
    finally:
        release.set()
        service.close()


def test_queued_request_freezes_request_parameters(tmp_path):
    from threading import Event

    (tmp_path / "images").mkdir()
    Image.new("RGB", (30, 20)).save(tmp_path / "images/a.png")
    project = Project(tmp_path)
    category = project.add_category("Object")
    image_id = project.images()[0]["id"]
    annotation = project.annotation(image_id)
    obj = Instance(class_id=category["id"], prompt_box=[2, 2, 26, 18])
    annotation.instances = [obj]
    project.save(image_id, annotation)
    service = SegmentationService(project, adapter=Adapter())
    release = Event()
    service.executor.submit(release.wait)
    try:
        body = SegmentRequest(instance_id=obj.id)
        pending = service.submit(image_id, body)
        body.instance_id = "changed-after-queueing"
        release.set()
        assert pending.result(timeout=5).instances[0].mask is not None
    finally:
        release.set()
        service.close()
