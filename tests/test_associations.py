import json

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from annodesk.app import create_app
from annodesk.associations import merge_imported_instances, segmentation_blocked_ids
from annodesk.domain import Annotation, Instance
from annodesk.execution import eligible as worker_eligible
from annodesk.inference import SegmentRequest, compute_annotation
from annodesk.masks import encode_mask
from annodesk.operations import eligible
from annodesk.statistics import StatisticsIndex
from annodesk.storage import Project


def polygon(box, category="cat"):
    x1, y1, x2, y2 = box
    return Instance(class_id=category, polygons=[[[x1, y1], [x2, y1], [x2, y2], [x1, y2]]])


def test_matches_reordered_labels_without_losing_unpaired_geometry():
    a = Instance(class_id="cat", box=[10, 10, 30, 30])
    b = Instance(class_id="cat", box=[60, 60, 90, 90])
    missing = Instance(class_id="dog", box=[1, 1, 5, 5])
    orphan = polygon([40, 40, 50, 50], "dog")
    masks = [polygon(b.box), orphan, polygon(a.box)]
    result = merge_imported_instances([a, b, missing, *masks])
    assert result == [a, b, missing, orphan]
    assert a.polygons == masks[2].polygons and b.polygons == masks[0].polygons
    assert a.box == [10, 10, 30, 30] and orphan.box is None
    assert not segmentation_blocked_ids(result)


@pytest.mark.parametrize("case", ["two-boxes", "two-masks", "loose-box"])
def test_ambiguous_overlaps_are_preserved_and_block_automatic_inference(case):
    box = Instance(class_id="cat", box=[10, 10, 30, 30])
    mask = polygon([10, 10, 30, 30])
    instances = [box, mask]
    if case == "two-boxes":
        instances.append(Instance(class_id="cat", box=[11, 11, 30, 30]))
    elif case == "two-masks":
        instances.append(polygon([11, 11, 30, 30]))
    else:
        box.box = [1, 1, 40, 40]
    before = [o.model_dump() for o in instances]
    assert [o.model_dump() for o in merge_imported_instances(instances)] == before
    assert box.id in segmentation_blocked_ids(instances)
    ann = Annotation(instances=instances)
    assert not eligible(ann, SegmentRequest())
    assert not worker_eligible(ann)


def test_different_classes_and_touching_edges_are_not_matched_or_blocked():
    box = Instance(class_id="cat", box=[10, 10, 30, 30])
    instances = [box, polygon(box.box, "dog"), polygon([30, 10, 40, 30])]
    assert len(merge_imported_instances(instances)) == 3
    assert not segmentation_blocked_ids(instances)


def test_existing_rle_masks_block_only_overlapping_boxes_and_explicit_refine_works():
    mask = np.zeros((100, 100), dtype=np.uint8)
    mask[10:30, 10:30] = 1
    a = Instance(class_id="cat", box=[10, 10, 30, 30])
    b = Instance(class_id="cat", box=[60, 60, 90, 90])
    ann = Annotation(instances=[a, b, Instance(class_id="cat", mask=encode_mask(mask))])
    before = ann.model_dump()
    calls = []

    class Adapter:
        def predict(self, _path, _model, box, *_args):
            calls.append(box)
            return [mask]

    assert segmentation_blocked_ids(ann.instances) == {a.id}
    assert eligible(ann, SegmentRequest())
    assert worker_eligible(ann)
    result = compute_annotation(
        None, (100, 100), ann.model_copy(deep=True), SegmentRequest(), Adapter()
    )
    assert calls == [b.box]
    assert result.instances[0].mask is None
    assert ann.model_dump() == before
    calls.clear()
    compute_annotation(
        None, (100, 100), ann.model_copy(deep=True), SegmentRequest(instance_id=a.id), Adapter()
    )
    assert calls == [a.box]
    blocked = Annotation(instances=[a, ann.instances[2]])
    with pytest.raises(ValueError, match="unassociated masks"):
        compute_annotation(None, (100, 100), blocked, SegmentRequest(), Adapter())


def dual_project(tmp_path):
    for folder in ["images", "labels", "labels_seg"]:
        (tmp_path / folder).mkdir()
    Image.new("RGB", (100, 80)).save(tmp_path / "images/a.png")
    (tmp_path / "labels/a.txt").write_text("0 0.5 0.5 0.6 0.6\n")
    (tmp_path / "labels_seg/a.txt").write_text("0 0.2 0.2 0.8 0.2 0.8 0.8 0.2 0.8\n")
    return Project(tmp_path)


def test_first_import_matches_statistics_and_does_not_rewrite_projections(tmp_path):
    project = dual_project(tmp_path)
    image_id = project.images()[0]["id"]
    paths = [project.label_path(image_id, seg) for seg in (False, True)]
    before = [p.read_bytes() for p in paths]
    index = object.__new__(StatisticsIndex)
    index.project = project
    record = index._imported(image_id)
    assert len(record["instances"]) == 1
    assert list(index._counts(record).values()) == [[1, 1, 1]]
    assert not project.annotation_path(image_id).exists()
    readonly = project.annotation(image_id, materialize=False)
    assert len(readonly.instances) == 1
    assert not eligible(readonly, SegmentRequest())
    assert not project.annotation_path(image_id).exists()
    ann = project.annotation(image_id)
    assert len(ann.instances) == 1 and ann.instances[0].box and ann.instances[0].polygons
    assert [p.read_bytes() for p in paths] == before
    assert project.annotation(image_id).instances[0].id == ann.instances[0].id


def test_existing_records_are_not_rewritten_and_api_exposes_blocked_boxes(tmp_path):
    project = dual_project(tmp_path)
    image_id = project.images()[0]["id"]
    ann = project.annotation(image_id)
    original = ann.instances[0]
    orphan = Instance(class_id=original.class_id, polygons=original.polygons)
    original.polygons = []
    ann.instances.append(orphan)
    ann.notes = "Keep manual edits"
    project.save(image_id, ann)
    path = project.annotation_path(image_id)
    before = path.read_bytes()
    with TestClient(create_app(project=tmp_path)) as client:
        response = client.get(f"/api/v1/images/{image_id}/annotation")
        assert response.status_code == 200
        data = response.json()
        assert len(data["instances"]) == 2 and data["notes"] == "Keep manual edits"
        assert data["segmentation_blocked"] == [original.id]
    assert path.read_bytes() == before
    assert "segmentation_blocked" not in json.loads(before)
