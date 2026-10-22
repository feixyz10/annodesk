import sys
from types import SimpleNamespace

import pytest

from annodesk.detector import DetectionAdapter
from tests.test_assistance import NAMES, fixture


def patch_yolo(monkeypatch, names, nc=3):
    devices = []

    class FakeYOLO:
        task = "detect"

        def __init__(self, *_args, **_kwargs):
            self.model = SimpleNamespace(model=[SimpleNamespace(nc=nc)], names=names)

        def to(self, device):
            devices.append(device)
            return self

    device = object()
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(device=lambda _: device))
    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=FakeYOLO))
    return device, devices


def test_checkpoint_and_class_file_are_checked_without_remapping(tmp_path, monkeypatch):
    _, registry = fixture(tmp_path)
    device, seen = patch_yolo(monkeypatch, NAMES)
    adapter = DetectionAdapter(registry, "cuda:1")
    assert adapter.load("det") == NAMES
    assert adapter.load("det") == NAMES
    assert seen == [device]
    (tmp_path / "classes.yaml").write_text("names: [dog, cat, bird]")
    with pytest.raises(ValueError, match="differ"):
        adapter.load("det")


def test_missing_checkpoint_names_require_matching_external_table(tmp_path, monkeypatch):
    _, registry = fixture(tmp_path)
    patch_yolo(monkeypatch, {0: "0", 1: "1", 2: "2"})
    assert DetectionAdapter(registry).load("det") == NAMES
    (tmp_path / "classes.yaml").write_text("names: [cat, dog]")
    with pytest.raises(ValueError, match="nc"):
        DetectionAdapter(registry).load("det")
    registry.config.models[0].classes_file = None
    with pytest.raises(ValueError, match="reliable class table"):
        DetectionAdapter(registry).load("det")
