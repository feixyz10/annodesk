"""Check the optional adapter contract without importing Torch or a real checkpoint."""

import sys
from types import ModuleType, SimpleNamespace

from annodesk.inference import UltralyticsAdapter
from tests.test_batch import dataset


def test_load_uses_predictors_config_and_torch_device(tmp_path, monkeypatch):
    registry = dataset(tmp_path)
    device_object = object()
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(device=lambda value: device_object))
    calls = []

    class Predictor:
        def __init__(self, overrides):
            assert overrides["device"] is device_object
            assert overrides["model"].endswith("sam2.1_s.pt")

        def setup_model(self, *, verbose):
            # SAM setup_model accepts a module or None, not a checkpoint string.
            calls.append(verbose)

    sam = ModuleType("ultralytics.models.sam")
    sam.Predictor = sam.SAM2Predictor = Predictor
    monkeypatch.setitem(sys.modules, "ultralytics.models.sam", sam)
    monkeypatch.setattr("annodesk.inference.importlib.util.find_spec", lambda name: True)
    adapter = UltralyticsAdapter(registry, "cuda:1")
    adapter.load("test")
    adapter.load("test")
    assert calls == [False]
