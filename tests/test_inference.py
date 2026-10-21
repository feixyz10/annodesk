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
