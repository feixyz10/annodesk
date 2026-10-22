import json

import numpy as np
from PIL import Image

from annodesk.batch import segment_dataset
from annodesk.cli import segment
from annodesk.inference import UltralyticsAdapter
from annodesk.models import ModelRegistry
from annodesk.storage import Project


def test_headless_converts_yolo_keeps_classes_and_resumes(tmp_path, monkeypatch):
    (tmp_path / "images/train/nested").mkdir(parents=True)
    (tmp_path / "labels/train/nested").mkdir(parents=True)
    Image.new("RGB", (30, 20)).save(tmp_path / "images/train/nested/a.png")
    label = tmp_path / "labels/train/nested/a.txt"
    label.write_text("2 0.5 0.5 0.8 0.8\n")
    (tmp_path / "model").mkdir()
    weights = tmp_path / "model/sam2.1_s.pt"
    weights.touch()
    cfg = tmp_path / "models.json"
    cfg.write_text(
        json.dumps(
            {
                "default_model": "test",
                "models": [
                    {"id": "test", "name": "Test", "backend": "sam2", "source": str(weights.parent)}
                ],
            }
        )
    )
    calls = []

    def predict(_self, path, model, box, points, text):
        calls.append((path, model, box))
        return [np.ones((20, 30), dtype=np.uint8)]

    monkeypatch.setattr(UltralyticsAdapter, "predict", predict)
    registry = ModelRegistry(cfg)
    first = segment_dataset(tmp_path, "", registry)
    assert first["processed"] == 1 and first["failed"] == []
    assert (tmp_path / "labels_seg/train/nested/a.txt").read_text().startswith("2 ")
    assert label.read_text().startswith("2 ")
    project = Project(tmp_path)
    obj = project.annotation(project.images()[0]["id"]).instances[0]
    assert obj.mask and obj.box and obj.class_id == project.metadata["classes"][2]["id"]
    second = segment_dataset(tmp_path, "", registry)
    assert second["processed"] == 0 and second["skipped"] == 1
    assert len(calls) == 1
    segment(tmp_path, models_config=cfg)  # CLI function shares the same headless path.


def test_headless_reports_failure_and_nonzero_exit(tmp_path, monkeypatch):
    import pytest

    (tmp_path / "images").mkdir()
    (tmp_path / "labels").mkdir()
    Image.new("RGB", (30, 20)).save(tmp_path / "images/a.png")
    label = tmp_path / "labels/a.txt"
    original = "0 0.5 0.5 0.8 0.8\n"
    label.write_text(original)
    (tmp_path / "model").mkdir()
    weights = tmp_path / "model/mobile_sam.pt"
    weights.touch()
    cfg = tmp_path / "models.json"
    cfg.write_text(
        json.dumps(
            {
                "default_model": "test",
                "models": [
                    {
                        "id": "test",
                        "name": "Test",
                        "backend": "mobile_sam",
                        "source": str(weights.parent),
                    }
                ],
            }
        )
    )

    def fail(*_args):
        raise ValueError("Missing local tokenizer")

    monkeypatch.setattr(UltralyticsAdapter, "predict", fail)
    with pytest.raises(SystemExit) as error:
        segment(tmp_path, models_config=cfg)
    assert error.value.code == 1
    report = json.loads((tmp_path / ".annodesk/segment-report.json").read_text())
    assert report["failed"][0]["error"] == "Missing local tokenizer"
    assert label.read_text() == original
    assert not (tmp_path / "labels_seg/a.txt").exists()
