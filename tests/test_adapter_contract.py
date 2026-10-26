"""Check the adapter contract without importing Torch or a real checkpoint."""

import sys
from types import ModuleType, SimpleNamespace

import pytest

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


def test_official_meta_sam2_checkpoint_uses_explicit_builder(tmp_path, monkeypatch):
    registry = dataset(tmp_path)
    (tmp_path / "model/sam2.1_s.pt").rename(tmp_path / "model/sam2.1_hiera_tiny.pt")
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(device=lambda value: value))
    calls = []
    module = object()

    class Predictor:
        def __init__(self, overrides):
            pass

        def setup_model(self, *, model, verbose):
            assert model is module
            calls.append(verbose)

    def builder(path):
        assert path == str(tmp_path / "model/sam2.1_hiera_tiny.pt")
        return module

    sam = ModuleType("ultralytics.models.sam")
    sam.Predictor = sam.SAM2Predictor = Predictor
    sam.build = SimpleNamespace(build_sam2_t=builder)
    monkeypatch.setitem(sys.modules, "ultralytics.models.sam", sam)
    monkeypatch.setattr("annodesk.inference.importlib.util.find_spec", lambda name: True)
    UltralyticsAdapter(registry, "mps").load("test")
    assert calls == [False]


def test_points_are_batched_as_one_instance_with_box(tmp_path, monkeypatch):
    from annodesk.domain import Point

    registry = dataset(tmp_path)
    adapter = UltralyticsAdapter(registry)
    monkeypatch.setattr(adapter, "_load", lambda *_: None)
    calls = []

    class Predictor:
        def set_image(self, path):
            pass

        def __call__(self, **kwargs):
            calls.append(kwargs)
            return []

    adapter.predictor = Predictor()
    adapter.predict(
        tmp_path / "images/train/nested/0.png",
        "test",
        [1, 1, 20, 18],
        [Point(x=10, y=10), Point(x=2, y=2, positive=False)],
        "",
    )
    assert calls[0]["points"] == [[[10, 10], [2, 2]]]
    assert calls[0]["labels"] == [[1, 0]]
    assert calls[0]["bboxes"] == [[1, 1, 20, 18]]
    assert calls[0]["multimask_output"] is False


@pytest.mark.parametrize("failure", ["constructor", "setup", "builder"])
@pytest.mark.parametrize("retry", ["test", "other"])
def test_failed_model_switch_invalidates_all_caches_and_can_retry(
    tmp_path, monkeypatch, failure, retry
):
    from annodesk.models import ModelEntry

    registry = dataset(tmp_path)
    other = tmp_path / "other"
    other.mkdir()
    weights = other / ("sam2_hiera_small.pt" if failure == "builder" else "other.pt")
    weights.write_bytes(b"fixture")
    registry.config.models.append(
        ModelEntry(id="other", name="Other", backend="sam2", source="other")
    )
    monkeypatch.setitem(sys.modules, "torch", SimpleNamespace(device=lambda value: value))
    monkeypatch.setattr("annodesk.inference.importlib.util.find_spec", lambda name: True)
    fail = True
    constructed = []

    class Predictor:
        def __init__(self, overrides):
            self.weights = overrides["model"]
            constructed.append(self.weights)
            if fail and self.weights == str(weights) and failure == "constructor":
                raise RuntimeError("Injected constructor failure")

        def setup_model(self, **kwargs):
            if fail and self.weights == str(weights) and failure == "setup":
                raise RuntimeError("Injected setup failure")

    def builder(_path):
        if fail:
            raise RuntimeError("Injected builder failure")
        return object()

    sam = ModuleType("ultralytics.models.sam")
    sam.Predictor = sam.SAM2Predictor = Predictor
    sam.build = SimpleNamespace(build_sam2_s=builder)
    monkeypatch.setitem(sys.modules, "ultralytics.models.sam", sam)
    adapter = UltralyticsAdapter(registry, "mps")
    adapter.load("test")
    first_predictor = adapter.predictor
    assert adapter.loaded_id == "test"
    adapter.image_key = ("old-image", 1, 10)
    with pytest.raises(RuntimeError, match="Injected"):
        adapter.load("other")
    assert adapter.predictor is None
    assert adapter.key is None
    assert adapter.image_key is None
    assert adapter.loaded_id == ""
    fail = False
    adapter.load(retry)
    assert adapter.predictor is not first_predictor
    assert adapter.predictor.weights == str(registry.weights(retry))
    assert adapter.key[0] == str(registry.weights(retry))
    assert adapter.image_key is None
    assert adapter.loaded_id == retry
    assert len(constructed) == 3
    # The successful retry is reusable; only the failed setup is discarded.
    adapter.load(retry)
    assert len(constructed) == 3
