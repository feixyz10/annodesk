import json

import pytest

from annodesk.exports import preview_export
from annodesk.lifecycle import export_project
from tests.test_lifecycle import make_project


def test_preview_counts_and_confirmation_staleness(tmp_path):
    project, image = make_project(tmp_path)
    plan = preview_export(project, "detection")
    assert plan["total"] == plan["counts"]["pending"] == 1
    assert plan["eligible"] == 0 and plan["skipped"]["pending"] == 1
    plan = preview_export(project, "detection", include_pending=True)
    assert plan["eligible"] == 1
    ann = project.annotation(image)
    ann.notes = "changed after confirmation"
    project.save(image, ann)
    with pytest.raises(ValueError, match="data changed"):
        export_project(
            project, "detection", include_pending=True, expected_signature=plan["signature"]
        )
    assert not (project.private / "exports").exists()


def test_custom_destination_repeat_and_integrity(tmp_path):
    project, image = make_project(tmp_path)
    target = tmp_path.parent / (tmp_path.name + "-export")
    plan = preview_export(project, "detection", include_pending=True, output=str(target))
    result = export_project(
        project,
        "detection",
        include_pending=True,
        output=plan["output"],
        expected_signature=plan["signature"],
    )
    assert result == target
    assert (result / "images/train/a.png").exists()
    assert (result / "labels/train/a.txt").read_text().startswith("0 ")
    again = preview_export(project, "detection", include_pending=True)
    assert again["already_exported"] and again["output"] == str(result)
    assert export_project(project, "detection", include_pending=True) == result
    (result / "labels/train/a.txt").write_text("broken")
    assert not preview_export(project, "detection", include_pending=True)["already_exported"]

    with pytest.raises(ValueError, match="already exists"):
        preview_export(project, "detection", include_pending=True, output=str(result))
    # A distinct requested location creates a new copy even when source data is unchanged.
    second = tmp_path.parent / (tmp_path.name + "-second")
    export_project(project, "detection", include_pending=True, output=str(second))
    ann = project.annotation(image)
    ann.detection_review = "ok"
    project.save(image, ann)
    assert not preview_export(project, "detection", include_pending=True)["already_exported"]


def test_cancelled_reuse_preserves_existing_export(tmp_path):
    project, _ = make_project(tmp_path)
    output = export_project(project, "detection", include_pending=True)
    before = {p.relative_to(output): p.read_bytes() for p in output.rglob("*") if p.is_file()}
    with pytest.raises(ValueError, match="Export cancelled"):
        export_project(project, "detection", include_pending=True, cancelled=lambda: True)
    assert {
        p.relative_to(output): p.read_bytes() for p in output.rglob("*") if p.is_file()
    } == before
    assert preview_export(project, "detection", include_pending=True)["already_exported"]


def test_preview_does_not_materialize_imported_records(tmp_path):
    project, image = make_project(tmp_path)
    project.annotation_path(image).unlink()
    plan = preview_export(project, "detection", include_pending=True)
    assert plan["eligible"] == 1
    assert not project.annotation_path(image).exists()
    output = export_project(
        project, "detection", include_pending=True, expected_signature=plan["signature"]
    )
    assert not project.annotation_path(image).exists()
    assert preview_export(project, "detection", include_pending=True)["already_exported"]
    assert json.loads((output / "report.json").read_text())["exported"] == 1


def test_review_and_empty_export_protection(tmp_path):
    project, image = make_project(tmp_path)
    ann = project.annotation(image)
    ann.detection_review = "uncertain"
    project.save(image, ann)
    plan = preview_export(project, "detection", include_pending=True)
    assert plan["counts"]["uncertain"] == 1 and plan["eligible"] == 0
    with pytest.raises(ValueError, match="No images qualify"):
        export_project(project, "detection", include_pending=True)
    assert not (project.private / "exports").exists()
    for target in (project.root, project.root / "copy", project.root / "images/copy"):
        with pytest.raises(ValueError, match="outside the working dataset"):
            preview_export(project, "detection", output=str(target))


def test_export_api_preview_and_target(tmp_path):
    from fastapi.testclient import TestClient

    from annodesk.app import create_app

    make_project(tmp_path)
    target = tmp_path.parent / (tmp_path.name + "-api-export")
    body = {"task": "detection", "include_pending": True, "output": str(target)}
    with TestClient(create_app(project=tmp_path)) as client:
        plan = client.post("/api/v1/export/preview", json=body)
        assert plan.status_code == 200, plan.text
        assert plan.json()["eligible"] == 1
        response = client.post(
            "/api/v1/export", json={**body, "expected_signature": plan.json()["signature"]}
        )
        assert response.status_code == 200, response.text
        assert response.json()["path"] == str(target)
        assert client.post("/api/v1/export/preview", json=body).json()["already_exported"]


def test_export_explains_unannotated_pending_image_and_explicit_empty(tmp_path):
    project, image = make_project(tmp_path)
    ann = project.annotation(image)
    ann.instances = []
    project.save(image, ann)
    plan = preview_export(project, "segmentation", include_pending=True)
    assert plan["total"] == plan["counts"]["pending"] == 1
    assert plan["eligible"] == 0
    assert plan["skipped"]["no_annotations"] == 1
    assert plan["skipped_images"] == [{"image": "train/a.png", "reason": "no_annotations"}]
    ann = project.annotation(image)
    ann.explicit_empty["segmentation"] = True
    project.save(image, ann)
    plan = preview_export(project, "segmentation", include_pending=True)
    assert plan["eligible"] == 1 and plan["skipped_images"] == []


def test_no_annotations_subcounts_are_independent_of_review_filter(tmp_path):
    project, image = make_project(tmp_path)
    ann = project.annotation(image)
    ann.instances = []
    ann.segmentation_review = "uncertain"
    project.save(image, ann)
    plan = preview_export(project, "segmentation")
    assert plan["counts"]["uncertain"] == plan["no_valid_annotations"]["uncertain"] == 1
    assert plan["skipped_by_state"]["uncertain"] == 1
    assert plan["skipped_no_valid_annotations"]["uncertain"] == 1
    assert sum(plan["skipped_by_state"].values()) == plan["total"] - plan["eligible"]
    assert plan["eligible"] == 0
    ann = project.annotation(image)
    ann.explicit_empty["segmentation"] = True
    project.save(image, ann)
    assert preview_export(project, "segmentation")["no_valid_annotations"]["uncertain"] == 0


def test_skipped_state_subsets_do_not_change_with_reason_priority(tmp_path):
    project, image = make_project(tmp_path)
    ann = project.annotation(image)
    ann.instances = []
    project.save(image, ann)
    for include_pending in (False, True):
        plan = preview_export(project, "segmentation", include_pending=include_pending)
        assert plan["skipped_by_state"]["pending"] == 1
        assert plan["skipped_no_valid_annotations"]["pending"] == 1
        assert plan["skipped"]["no_annotations" if include_pending else "pending"] == 1
