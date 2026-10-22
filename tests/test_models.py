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
