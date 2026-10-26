"""Candidate proposals are read-only; only an explicit selection can commit."""

from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from annodesk.app import create_app
from annodesk.candidates import (
    CandidateApply,
    CandidateRequest,
    apply_candidate,
    preview_candidates,
)
from annodesk.inference import SegmentationService, SegmentRequest, UltralyticsAdapter
from annodesk.masks import decode_mask
from annodesk.storage import Project, RevisionConflict
from tests.test_batch import dataset


class Candidates:
    def predict_candidates(self, *_):
        outer = np.zeros((20, 30), dtype=np.uint8)
        outer[2:18, 3:25] = 1
        inner = outer.copy()
        inner[7:12, 9:16] = 0
        return [(outer, 0.5), (inner, 0.96), (outer, None), (outer, float("nan"))]


def setup(root, *, mask_only=True):
    registry = dataset(root)
    project = Project(root)
    image_id = next(iter(project.entries))
    annotation = project.annotation(image_id)
    obj = annotation.instances[0]
    if mask_only:
        obj.prompt_box, obj.box = obj.box, None
    annotation.detection_review = annotation.segmentation_review = "ok"
    annotation.explicit_empty["segmentation"] = True
    if mask_only:
        annotation.explicit_empty["detection"] = True
    annotation = project.save(image_id, annotation)
    body = CandidateRequest(
        model="test",
        instance_id=obj.id,
        expected_revision=annotation.revision,
        project_id=project.metadata["id"],
    )
    return project, registry, image_id, body


def apply_body(response, index=0):
    return CandidateApply(**{**response, "mask": response["items"][index]["mask"]})


def test_readonly_sorted_candidates_then_explicit_mask_only_commit(tmp_path):
    project, _, image_id, body = setup(tmp_path)
    original = project.annotation(image_id).model_dump()
    before = {
        p: p.read_bytes()
        for p in [
            project.annotation_path(image_id),
            project.label_path(image_id),
            project.label_path(image_id, True),
        ]
        if p.exists()
    }
    response = preview_candidates(project, image_id, body, Candidates())
    assert [item["quality"] for item in response["items"]] == [0.96, 0.5, None]
    assert len(response["items"]) == 3
    assert response["items"][0]["overlay"].startswith("data:image/png;base64,")
    assert project.annotation(image_id).model_dump() == original
    assert all(path.read_bytes() == value for path, value in before.items())
    saved = apply_candidate(project, image_id, apply_body(response))
    obj = saved.instances[0]
    assert obj.id == body.instance_id and obj.class_id == original["instances"][0]["class_id"]
    assert obj.box is None and obj.prompt_box == original["instances"][0]["prompt_box"]
    assert not decode_mask(obj.mask)[8, 10]  # A hole survives PNG preview and RLE commit.
    assert saved.detection_review == "ok" and saved.segmentation_review == "pending"
    assert not saved.explicit_empty["segmentation"]
    assert project.label_path(image_id).read_text() == ""


@pytest.mark.parametrize("conflict", ["revision", "image", "labels"])
def test_stale_application_preserves_data(tmp_path, conflict):
    project, _, image_id, body = setup(tmp_path, mask_only=False)
    response = preview_candidates(project, image_id, body, Candidates())
    if conflict == "revision":
        edited = project.annotation(image_id)
        edited.notes = "new human edit"
        project.save(image_id, edited)
    elif conflict == "image":
        Image.new("RGB", (30, 20), "red").save(project.image_path(image_id))
    else:
        project.label_path(image_id).write_text("2 0.5 0.5 0.4 0.4\n")
    with pytest.raises((RevisionConflict, ValueError)):
        apply_candidate(project, image_id, apply_body(response))
    assert not __import__("json").loads(project.annotation_path(image_id).read_text())["instances"][
        0
    ]["mask"]


@pytest.mark.parametrize(
    "reason", ["locked", "hidden", "excluded", "no_prompt", "text", "unsupported"]
)
def test_invalid_preview_never_changes_annotation(tmp_path, reason):
    project, _, image_id, body = setup(tmp_path)
    ann = project.annotation(image_id)
    if reason == "locked":
        ann.instances[0].locked = True
    if reason == "hidden":
        ann.instances[0].hidden = True
    if reason == "excluded":
        ann.excluded = True
    if reason == "no_prompt":
        ann.instances[0].prompt_box = None
    ann = project.save(image_id, ann)
    body.expected_revision = ann.revision
    if reason == "text":
        body.text = "object"
    with pytest.raises(ValueError):
        preview_candidates(
            project, image_id, body, object() if reason == "unsupported" else Candidates()
        )
    assert project.annotation(image_id).revision == ann.revision


def test_empty_or_wrong_size_masks_are_not_offered(tmp_path):
    project, _, image_id, body = setup(tmp_path)
    for binary in [np.zeros((20, 30), dtype=np.uint8), np.ones((2, 3), dtype=np.uint8)]:
        adapter = SimpleNamespace(predict_candidates=lambda *_, binary=binary: [(binary, 0.8)])
        with pytest.raises(ValueError):
            preview_candidates(project, image_id, body, adapter)
    response = preview_candidates(project, image_id, body, Candidates())
    empty = response["items"][0]["mask"].copy()
    empty["size"] = [2, 3]
    with pytest.raises(ValueError):
        apply_candidate(project, image_id, apply_body({**response, "items": [{"mask": empty}]}))


def test_adapter_explicit_modes_and_quality_alignment(tmp_path, monkeypatch):
    registry = dataset(tmp_path)
    adapter = UltralyticsAdapter(registry)
    monkeypatch.setattr(adapter, "_load", lambda *_: None)
    calls = []

    class Tensor:
        def __init__(self, data):
            self.data = np.asarray(data)

        def cpu(self):
            return self

        def numpy(self):
            return self.data

        def tolist(self):
            return self.data.tolist()

    class Predictor:
        def set_image(self, *_):
            pass

        def __call__(self, **kwargs):
            calls.append(kwargs)
            return [
                SimpleNamespace(
                    masks=SimpleNamespace(
                        data=[Tensor(np.ones((20, 30))), Tensor(np.zeros((20, 30)))]
                    ),
                    boxes=SimpleNamespace(conf=Tensor([0.8, 0.6])),
                )
            ]

    adapter.predictor = Predictor()
    path = tmp_path / "images/train/nested/0.png"
    single = adapter._predict(path, registry.weights("test"), "sam2", [1, 1, 8, 8], [], "")
    multiple = adapter._predict(
        path, registry.weights("test"), "sam2", [1, 1, 8, 8], [], "", candidates=True
    )
    adapter._predict(path, registry.weights("test"), "sam3", None, [], "object")
    assert calls[0]["multimask_output"] is False
    assert calls[1]["multimask_output"] is True
    assert "multimask_output" not in calls[2]
    assert [score for _, score in multiple] == [0.8, 0.6]
    assert len(single) == 2  # Selection policy remains in the coordinator, not the adapter.
    assert not hasattr(SegmentRequest(multimask_output=True), "multimask_output")


def test_http_candidates_preview_and_apply(tmp_path, monkeypatch):
    project, registry, image_id, body = setup(tmp_path)
    monkeypatch.setattr(SegmentationService, "configure", lambda self, request: request)
    monkeypatch.setattr(UltralyticsAdapter, "predict_candidates", Candidates().predict_candidates)
    with TestClient(create_app(project=tmp_path, models_config=registry.path)) as client:
        assert client.get("/api/v1/models").json()["models"][0]["mask_candidates"]
        response = client.post(f"/api/v1/images/{image_id}/mask-candidates", json=body.model_dump())
        assert response.status_code == 200, response.text
        selected = apply_body(response.json(), 1)
        saved = client.post(
            f"/api/v1/images/{image_id}/mask-candidates/apply", json=selected.model_dump()
        )
        assert saved.status_code == 200, saved.text
        assert decode_mask(saved.json()["instances"][0]["mask"])[8, 10]
        assert (
            client.post(
                f"/api/v1/images/{image_id}/mask-candidates/apply", json=selected.model_dump()
            ).status_code
            == 409
        )


def test_preview_rejects_an_annotation_changed_during_inference(tmp_path):
    project, _, image_id, body = setup(tmp_path)

    class EditingAdapter(Candidates):
        def predict_candidates(self, *_):
            ann = project.annotation(image_id)
            ann.notes = "human edit while inference runs"
            project.save(image_id, ann)
            return super().predict_candidates()

    with pytest.raises(RevisionConflict):
        preview_candidates(project, image_id, body, EditingAdapter())
    assert project.annotation(image_id).notes == "human edit while inference runs"
    assert not project.annotation(image_id).instances[0].mask


def test_batch_rejects_semantic_text_instead_of_multi_object_output(tmp_path):
    from annodesk.batch import new_report, run_batch
    from annodesk.events import EventLog

    project, registry, _, _ = setup(tmp_path)
    body = SegmentRequest(model="test", text="object")
    report = new_report(project, body)
    with pytest.raises(ValueError, match="single masks"):
        run_batch(project, registry, body, report, EventLog(), lambda: None)
    assert report["status"] == "failed" and report["processed"] == 0


def test_single_mask_prompt_preview_uses_predict_and_never_writes(tmp_path):
    project, _, image_id, body = setup(tmp_path)
    original = project.annotation(image_id).model_dump()

    class Single:
        def predict(self, path, model, box, points, text):
            assert model == "test" and box and text == ""
            mask = np.zeros((20, 30), dtype=np.uint8)
            mask[2:8, 3:9] = 1
            return [mask, mask]

        def predict_candidates(self, *_):
            pytest.fail("Single-mask interaction must not call multimask inference")

    result = preview_candidates(
        project, image_id, body.model_copy(update={"multimask_output": False}), Single()
    )
    assert len(result["items"]) == 1
    assert result["items"][0]["quality"] is None
    assert decode_mask(result["items"][0]["mask"]).sum() == 36
    assert project.annotation(image_id).model_dump() == original
