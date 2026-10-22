import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from annodesk.app import create_app


def test_cli_help_does_not_import_torch():
    result = subprocess.run(
        [sys.executable, "-m", "annodesk", "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0
    assert "serve" in result.stdout
    assert "doctor" in result.stdout


@pytest.mark.parametrize("config_state", ["missing", "broken"])
def test_geometry_cli_does_not_require_model_configuration(tmp_path, monkeypatch, config_state):
    import json

    from PIL import Image

    from annodesk.domain import Instance
    from annodesk.storage import Project

    (tmp_path / "images").mkdir()
    Image.new("RGB", (20, 10)).save(tmp_path / "images/a.png")
    project = Project(tmp_path)
    category = project.add_category("Object")
    image_id = next(iter(project.entries))
    ann = project.annotation(image_id)
    ann.instances = [Instance(class_id=category["id"], polygons=[[[1, 1], [8, 1], [8, 8]]])]
    project.save(image_id, ann)
    config = tmp_path / "models.json"
    if config_state == "broken":
        config.write_text("not valid json")
    monkeypatch.setenv("ANNODESK_MODELS_CONFIG", str(config))
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "annodesk",
            "boxes-from-masks",
            "--project",
            str(tmp_path),
            "--log-dir",
            str(tmp_path / "logs"),
        ],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["boxes_added"] == 1
    assert Project(tmp_path).annotation(image_id).instances[0].box == [1, 1, 8, 8]


def test_static_runtime_configuration():
    client = TestClient(create_app(mode="ui", api_url="http://gpu-host:8765"))
    assert client.get("/ui-config.json").json()["apiBase"] == "http://gpu-host:8765/api/v1"
    assert client.get("/").status_code == 200
    assert client.get("/api/v1/info").status_code == 404


def test_api_only():
    client = TestClient(create_app(mode="api"))
    assert client.get("/").status_code == 404
    assert client.get("/api/v1/info").json()["protocol"] == 1


def test_user_guide_print_and_export(tmp_path, capsys):
    import pytest

    from annodesk.cli import docs

    docs()
    printed = capsys.readouterr().out
    assert "AnnoDesk 用户指南" in printed
    assert "annodesk segment --project" in printed
    output = tmp_path / "guide.md"
    docs(output)
    assert output.read_text() == printed
    with pytest.raises(SystemExit, match="already exists"):
        docs(output)
    assert output.read_text() == printed


def test_workbench_html_is_always_fresh_even_with_old_browser_validators():
    for mode in ("serve", "ui"):
        client = TestClient(create_app(mode=mode))
        for path in ("/", "/index.html"):
            response = client.get(path)
            assert response.headers.get("cache-control") == "no-store"
            assert "etag" not in response.headers
            for validators in (
                {"If-Modified-Since": "Thu, 31 Dec 2099 23:59:59 GMT"},
                {"If-None-Match": '"old-build"'},
            ):
                fresh = client.get(path, headers=validators)
                assert fresh.status_code == 200
                assert fresh.text == response.text


def test_project_state_and_errors_cannot_be_cached():
    client = TestClient(create_app())
    for path, status in (("/api/v1/project", 200), ("/api/v1/images", 409)):
        response = client.get(path)
        assert response.status_code == status
        assert response.headers.get("cache-control") == "no-store"
