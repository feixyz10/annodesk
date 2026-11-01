import numpy as np
import pytest
from PIL import Image

from annodesk.domain import Annotation, Instance
from annodesk.inference import SegmentRequest, compute_annotation
from annodesk.operations import eligible, preview
from annodesk.storage import Project


def test_manual_protection_survives_save_and_skips_empty_mask(tmp_path):
    (tmp_path / "images").mkdir()
    Image.new("RGB", (10, 10)).save(tmp_path / "images/a.png")
    project = Project(tmp_path)
    image_id = project.images()[0]["id"]
    ann = project.annotation(image_id)
    obj = Instance(box=[1, 1, 8, 8], mask_manually_edited=True)
    ann.instances = [obj]
    saved = project.save(image_id, ann)
    assert saved.instances[0].model_dump()["mask_manually_edited"] is True
    assert not eligible(saved, SegmentRequest())
    report = preview(project, SegmentRequest())
    assert report["counts"]["manual_edits_protected"] == 1


def test_direct_inference_cannot_replace_protected_mask_but_other_boxes_work():
    protected = Instance(box=[1, 1, 8, 8], mask_manually_edited=True)
    other = Instance(box=[2, 2, 9, 9])
    ann = Annotation(instances=[protected, other])

    class Adapter:
        def predict(self, *_):
            return [np.ones((10, 10), dtype=np.uint8)]

    with pytest.raises(ValueError, match="preview"):
        compute_annotation(
            None,
            (10, 10),
            ann.model_copy(deep=True),
            SegmentRequest(instance_id=protected.id),
            Adapter(),
        )
    result = compute_annotation(None, (10, 10), ann, SegmentRequest(), Adapter())
    assert result.instances[0].mask is None
    assert result.instances[1].mask
