import json
import socket
import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from annodesk.app import create_app
from annodesk.models import ModelRegistry
from annodesk.offline import offline_inference


def config(tmp_path, source="org/repo"):
    path = tmp_path / "models.json"
    entry = {"id": "local", "name": "Local SAM", "backend": "sam2", "source": str(source)}
    path.write_text(json.dumps({"default_model": "local", "models": [entry]}))
    return path


def test_config_relative_then_hf_models_fallback(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    remote = cache / "org/repo"
    remote.mkdir(parents=True)
    (remote / "sam2.1_s.pt").write_bytes(b"test")
    monkeypatch.setenv("HF_MODELS", str(cache))
    registry = ModelRegistry(config(tmp_path))
    assert registry.resolve("") == remote
    assert registry.weights("") == remote / "sam2.1_s.pt"
    local = tmp_path / "org/repo"
    local.mkdir(parents=True)
    # Existing local directories take precedence; do not hide a missing checkpoint.
    with pytest.raises(ValueError, match="No download"):
        registry.weights("local")
    (local / "sam2.1_s.pt").write_bytes(b"local")
    assert registry.resolve("local") == local
    assert registry.weights("local") == local / "sam2.1_s.pt"
    assert registry.describe()["models"][0]["available"]


def test_absolute_directory_and_weight_files_are_not_sources(tmp_path, monkeypatch):
    directory = tmp_path / "model"
    directory.mkdir()
    weights = directory / "sam2.1_s.pt"
    weights.touch()
    registry = ModelRegistry(config(tmp_path, directory))
    assert registry.resolve("local") == directory
    assert registry.weights("local") == weights
    # Absolute paths never accidentally resolve beneath HF_MODELS.
    monkeypatch.setenv("HF_MODELS", str(tmp_path / "cache"))
    with pytest.raises(ValueError, match="must be a directory"):
        ModelRegistry(config(tmp_path, weights)).resolve("local")
    with pytest.raises(ValueError, match="Unknown model"):
        registry.resolve("https://example.invalid/model")
    with pytest.raises(ValueError, match="URLs"):
        ModelRegistry(config(tmp_path, "https://example.invalid/model"))


def test_existing_local_file_does_not_hide_hf_directory(tmp_path, monkeypatch):
    (tmp_path / "repo").touch()
    remote = tmp_path / "cache/repo"
    remote.mkdir(parents=True)
    monkeypatch.setenv("HF_MODELS", str(tmp_path / "cache"))
    assert ModelRegistry(config(tmp_path, "repo")).resolve("local") == remote


def test_directory_with_ambiguous_or_incompatible_weights_is_unavailable(tmp_path):
    directory = tmp_path / "repo"
    directory.mkdir()
    registry = ModelRegistry(config(tmp_path, "repo"))
    (directory / "model.safetensors").touch()
    with pytest.raises(ValueError, match="safetensors-only"):
        registry.weights("local")
    for name in ("sam2.1_s.pt", "sam2.1_l.pt"):
        (directory / name).touch()
    with pytest.raises(ValueError, match="Multiple checkpoint"):
        registry.weights("local")
    assert not registry.describe()["models"][0]["available"]


def test_status_models_available_without_project_and_reload(tmp_path):
    path = config(tmp_path, "repo")
    client = TestClient(create_app(models_config=path))
    assert client.get("/api/v1/project").status_code == 200
    assert client.get("/api/v1/project").json() is None
    assert not client.get("/api/v1/models").json()["models"][0]["available"]
    (tmp_path / "repo").mkdir()
    (tmp_path / "repo/sam2.1_s.pt").touch()
    value = json.loads(path.read_text())
    value["models"][0]["name"] = "Updated name"
    path.write_text(json.dumps(value))
    updated = client.get("/api/v1/models").json()["models"][0]
    assert updated["available"] and updated["name"] == "Updated name"
    assert client.get("/api/v1/images").status_code == 409


def test_offline_guard_blocks_network_and_auto_install_without_requests(monkeypatch):
    for key in (
        "HF_HUB_OFFLINE",
        "TRANSFORMERS_OFFLINE",
        "YOLO_OFFLINE",
        "YOLO_AUTOINSTALL",
        "YOLO_VERBOSE",
    ):
        monkeypatch.setenv(key, "false")
    with offline_inference():
        with pytest.raises(RuntimeError, match="disabled"):
            socket.create_connection(("127.0.0.1", 9))
        with pytest.raises(RuntimeError, match="disabled"):
            subprocess.run([sys.executable, "-m", "pip", "--version"], check=True)
    # The hook must stop guarding once inference finishes, even after errors.
    assert subprocess.run([sys.executable, "-c", "pass"], check=False).returncode == 0


def test_shipped_presets_and_bundled_detector(tmp_path, monkeypatch):
    import hashlib
    from pathlib import Path

    import annodesk.models as models

    root = Path(__file__).resolve().parents[1]
    monkeypatch.delenv("HF_MODELS", raising=False)
    monkeypatch.setattr(models, "missing_inference_dependencies", lambda: [])
    registry = ModelRegistry(root / "models.json")
    assert registry.config.default_model == "facebook/sam2.1-hiera-tiny"
    assert registry.config.default_detection_model == "yolo11n"
    for entry in registry.config.models:
        if entry.task == "segmentation":
            assert "/" in entry.id
            assert entry.source == entry.id
    checkpoint = registry.weights("yolo11n")
    assert checkpoint == root / "assets/models/yolo11n/yolo11n.pt"
    assert hashlib.sha256(checkpoint.read_bytes()).hexdigest() == (
        "0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1"
    )
    # Check the actual preset, including HF_MODELS fallback, without loading a runtime.
    hf = tmp_path / "hf"
    model = hf / registry.config.default_model
    model.mkdir(parents=True)
    (model / "sam2.1_hiera_tiny.pt").touch()
    monkeypatch.setenv("HF_MODELS", str(hf))
    assert registry.weights("") == model / "sam2.1_hiera_tiny.pt"
    assert registry.startup_warnings() == []


def test_startup_warns_about_missing_sam_even_when_detector_available(tmp_path, monkeypatch):
    import annodesk.models as models
    from annodesk.events import EventLog

    path = config(tmp_path)
    value = json.loads(path.read_text())
    detector = tmp_path / "detector"
    detector.mkdir()
    (detector / "yolo11n.pt").touch()
    value["default_detection_model"] = "yolo11n"
    value["models"].append(
        {"id": "yolo11n", "name": "YOLO11n", "backend": "ultralytics", "source": "detector"}
    )
    path.write_text(json.dumps(value))
    monkeypatch.setattr(models, "missing_inference_dependencies", lambda: [])
    events = EventLog()
    with TestClient(create_app(models_config=path, events=events)) as client:
        warnings = [event for event in events.events if event["event_type"] == "model_setup"]
        assert len(warnings) == 1
        assert "segmentation model local was not found locally" in warnings[0]["message"]
        assert "HF_MODELS" not in warnings[0]["message"]
        assert "models.json" in warnings[0]["message"]
        assert "Manual annotation remains available" in warnings[0]["message"]
        for _ in range(2):
            assert client.get("/api/v1/models").status_code == 200
        assert len(events.events) == 1  # Polling/Reload does not repeat startup warnings.


def test_missing_dependencies_are_distinct_from_weight_availability(tmp_path, monkeypatch):
    import annodesk.models as models

    monkeypatch.setattr(models.importlib.util, "find_spec", lambda name: None)
    folder = tmp_path / "repo"
    folder.mkdir()
    (folder / "sam2.1_s.pt").touch()
    registry = ModelRegistry(config(tmp_path, "repo"))
    value = registry.describe()
    assert value["models"][0]["available"]
    assert value["missing_dependencies"] == ["torch", "ultralytics"]
    warnings = registry.startup_warnings()
    assert not any(
        "segmentation model local was not found locally" in message for message in warnings
    )
    assert any(
        "pip install" in message and "annodesk[inference]" in message for message in warnings
    )
    assert not any(name in sys.modules for name in ("torch", "ultralytics"))


def grouped_config():
    return {
        "segmentation": {
            "default_model": "org/sam",
            "models": [{"id": "org/sam", "name": "SAM", "backend": "sam2", "source": "org/sam"}],
        },
        "detection": {
            "default_model": "yolo11n",
            "models": [
                {"id": "yolo11n", "name": "YOLO", "backend": "ultralytics", "source": "detector"}
            ],
        },
    }


def test_grouped_configuration_preserves_internal_and_worker_protocol(tmp_path, monkeypatch):
    from annodesk.models import ModelConfig

    raw = grouped_config()
    path = tmp_path / "models.json"
    path.write_text(json.dumps(raw))
    cache = tmp_path / "hf"
    sam = cache / "org/sam"
    sam.mkdir(parents=True)
    (sam / "sam2.1_s.pt").touch()
    detector = tmp_path / "detector"
    detector.mkdir()
    (detector / "yolo11n.pt").touch()
    monkeypatch.setenv("HF_MODELS", str(cache))
    registry = ModelRegistry(path)
    assert registry.entry("").id == "org/sam"
    assert registry.entry("", "detection").id == "yolo11n"
    assert registry.weights("org/sam") == sam / "sam2.1_s.pt"
    assert registry.weights("yolo11n") == detector / "yolo11n.pt"
    frozen = registry.freeze()
    # Spawn workers consume the existing normalized protocol, not the on-disk schema.
    assert ModelConfig.model_validate(frozen.config.model_dump()) == registry.config
    with TestClient(create_app(models_config=path)) as client:
        response = client.get("/api/v1/models").json()
        assert response["default_model"] == "org/sam"
        assert response["default_detection_model"] == "yolo11n"
        assert [entry["task"] for entry in response["models"]] == ["segmentation", "detection"]
    assert (
        json.loads(path.read_text()) == raw
    )  # Reading/reloading never rewrites user configuration.


@pytest.mark.parametrize("task", ["segmentation", "detection"])
def test_grouped_single_task_and_implicit_default(task):
    from annodesk.models import ModelConfig

    group = grouped_config()[task]
    group.pop("default_model")
    config = ModelConfig.model_validate({task: group})
    expected = group["models"][0]["id"]
    assert (
        config.default_model if task == "segmentation" else config.default_detection_model
    ) == expected
    assert len(config.models) == 1


@pytest.mark.parametrize(
    "failure",
    ["mixed", "wrong_task", "wrong_default", "duplicate", "unknown_root", "unknown_group", "empty"],
)
def test_grouped_configuration_rejects_ambiguous_or_invalid_definitions(failure):
    from annodesk.models import ModelConfig

    raw = grouped_config()
    if failure == "mixed":
        raw["models"] = []
    elif failure == "wrong_task":
        raw["detection"]["models"] = raw["segmentation"]["models"]
    elif failure == "wrong_default":
        raw["segmentation"]["default_model"] = "yolo11n"
    elif failure == "duplicate":
        raw["detection"]["models"][0]["id"] = "org/sam"
    elif failure == "unknown_root":
        raw["typo"] = {}
    elif failure == "unknown_group":
        raw["segmentation"]["defualt_model"] = "org/sam"
    else:
        raw = {"segmentation": {}, "detection": {}}
    with pytest.raises(ValueError):
        ModelConfig.model_validate(raw)
