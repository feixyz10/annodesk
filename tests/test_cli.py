import subprocess
import sys

from fastapi.testclient import TestClient

from annodesk.app import create_app


def test_cli_help_does_not_import_torch():
    result = subprocess.run(
        [sys.executable, "-m", "annodesk", "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "serve" in result.stdout
    assert "doctor" in result.stdout


def test_static_runtime_configuration():
    client = TestClient(create_app(mode="ui", api_url="http://gpu-host:8765"))
    assert client.get("/ui-config.json").json()["apiBase"] == "http://gpu-host:8765/api/v1"
    assert client.get("/").status_code == 200
    assert client.get("/api/v1/info").status_code == 404


def test_api_only():
    client = TestClient(create_app(mode="api"))
    assert client.get("/").status_code == 404
    assert client.get("/api/v1/info").json()["protocol"] == 1
