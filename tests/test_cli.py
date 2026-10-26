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
    assert "build-ui" not in result.stdout
    assert "{serve,segment,detect,boxes-from-masks,ui,models,doctor,docs}" in result.stdout
    assert "Start the workbench with serve" in result.stdout


@pytest.mark.parametrize(
    "command",
    ["serve", "segment", "detect", "boxes-from-masks", "ui", "models", "doctor", "docs"],
)
def test_user_command_help_remains_lazy(command):
    code = """
import importlib.abc
import runpy
import sys

class BlockModels(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'torch', 'ultralytics'}:
            raise AssertionError('Help imported an inference dependency: ' + fullname)

sys.meta_path.insert(0, BlockModels())
sys.argv = ['annodesk', sys.argv[1], '--help']
runpy.run_module('annodesk', run_name='__main__')
"""
    result = subprocess.run([sys.executable, "-c", code, command], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert "options" in result.stdout


def test_developer_build_command_is_not_exposed():
    result = subprocess.run(
        [sys.executable, "-m", "annodesk", "build-ui"], capture_output=True, text=True
    )
    assert result.returncode == 2
    assert "build-ui" in result.stderr


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


@pytest.mark.parametrize(
    ("lang", "title"), [("en", "AnnoDesk User Guide"), ("zh-CN", "AnnoDesk 用户指南")]
)
def test_user_guide_print_and_export(tmp_path, capsys, lang, title):
    from annodesk.cli import docs

    options = {} if lang == "en" else {"lang": lang}
    docs(**options)
    printed = capsys.readouterr().out
    assert title in printed
    assert "annodesk segment --project" in printed
    output = tmp_path / "guide.md"
    docs(output, **options)
    assert output.read_text() == printed
    with pytest.raises(SystemExit, match="already exists"):
        docs(output, **options)
    assert output.read_text() == printed


def test_chinese_guide_is_available_through_cli():
    result = subprocess.run(
        [sys.executable, "-m", "annodesk", "docs", "--lang", "zh-CN"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("# AnnoDesk 用户指南")


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


@pytest.mark.parametrize(
    ("command", "explanations"),
    [
        (
            "serve",
            ["start without a project", "ANNODESK_MODELS_CONFIG", "~/.cache/annodesk", "0.0.0.0"],
        ),
        ("ui", ["without /api/v1", "reachable from the user's browser", "Backend logs remain"]),
        (
            "segment",
            [
                "segmentation.default_model",
                "CUDA_VISIBLE_DEVICES",
                "one worker per selected CUDA device",
                "Not reviewed",
            ],
        ),
        (
            "detect",
            [
                "detection.default_model",
                "consider all model classes",
                "preserves existing annotations",
                "Non-maximum suppression",
            ],
        ),
        (
            "boxes-from-masks",
            [
                "create only missing boxes",
                "locked instances are always skipped",
                "~/.cache/annodesk",
            ],
        ),
        ("models", ["ANNODESK_MODELS_CONFIG", "creates no log files"]),
        ("docs", ["print the installed guide to the terminal", "never overwritten"]),
    ],
)
def test_cli_help_explains_parameters_and_omitted_values(command, explanations):
    result = subprocess.run(
        [sys.executable, "-m", "annodesk", command, "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    text = " ".join(result.stdout.replace("│", " ").split())
    for explanation in explanations:
        assert explanation in text
    if command == "models":
        assert "--log-dir" not in text and "--log-level" not in text


@pytest.mark.parametrize(
    ("command", "explanations"),
    [
        (
            "serve",
            [
                "computer that reads/writes the dataset",
                "http://SERVER_IP:8765",
                "No separate ui command is needed",
                "remote inference is not supported",
            ],
        ),
        (
            "ui",
            [
                "http://127.0.0.1:8080",
                "browser calls --api-url directly",
                "ui does not open local datasets",
                "serve already provides both",
            ],
        ),
    ],
)
def test_deployment_help_explains_machine_roles_and_browser_addresses(command, explanations):
    result = subprocess.run(
        [sys.executable, "-m", "annodesk", command, "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stderr
    text = " ".join(result.stdout.replace("│", " ").split())
    for explanation in explanations:
        assert explanation in text


def test_separate_ui_does_not_own_the_browsers_local_dataset(tmp_path, monkeypatch):
    from PIL import Image

    server = tmp_path / "server-dataset"
    local = tmp_path / "local-dataset"
    for directory in (server, local):
        (directory / "images").mkdir(parents=True)
        Image.new("RGB", (12, 8)).save(directory / "images/a.png")
    monkeypatch.chdir(local)
    with TestClient(create_app(mode="api", project=server)) as api_client:
        with TestClient(create_app(mode="ui", api_url="http://gpu-server:8765")) as ui_client:
            assert ui_client.get("/").status_code == 200
            assert (
                ui_client.get("/ui-config.json").json()["apiBase"]
                == "http://gpu-server:8765/api/v1"
            )
            assert ui_client.get("/api/v1/project").status_code == 404
            assert api_client.get("/").status_code == 404
            assert api_client.get("/api/v1/project").json()["root"] == str(server)
            assert not (local / ".annodesk").exists()


@pytest.mark.parametrize("api_only", [False, True])
def test_serve_api_only_controls_page_hosting(tmp_path, monkeypatch, api_only):
    from annodesk.cli import serve

    def run(app, host, port):
        assert (host, port) == ("127.0.0.1", 8765)
        with TestClient(app) as client:
            assert client.get("/api/v1/info").status_code == 200
            assert client.get("/").status_code == (404 if api_only else 200)
            assert client.get("/ui-config.json").status_code == (404 if api_only else 200)

    monkeypatch.setattr("annodesk.cli._run_server", run)
    serve(api_only=api_only, log_dir=tmp_path / "logs")


def test_api_only_cannot_open_a_nonexistent_workbench(monkeypatch):
    from annodesk.cli import serve

    monkeypatch.setattr("annodesk.cli.webbrowser.open", lambda *_: pytest.fail("Browser opened"))
    monkeypatch.setattr("annodesk.cli._logging", lambda *_: pytest.fail("Logging initialized"))
    with pytest.raises(SystemExit, match="--open cannot be combined with --api-only"):
        serve(api_only=True, open=True)


def test_removed_api_command_explains_replacement_in_help():
    rejected = subprocess.run(
        [sys.executable, "-m", "annodesk", "api"], capture_output=True, text=True
    )
    assert rejected.returncode == 2
    result = subprocess.run(
        [sys.executable, "-m", "annodesk", "serve", "--help"], capture_output=True, text=True
    )
    assert result.returncode == 0
    text = " ".join(result.stdout.replace("│", " ").split())
    assert "--api-only" in text and "without a workbench page" in text
