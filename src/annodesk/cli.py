"""Typed console commands. Heavy inference imports are intentionally lazy."""

import importlib.util
import json
import subprocess
import webbrowser
from pathlib import Path
from typing import Annotated, Literal

import tyro


def serve(
    project: Path | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    open: bool = False,
    models_config: Path | None = None,
) -> None:
    """Start the annotation API and bundled workbench."""
    import uvicorn

    from annodesk.app import create_app

    if open:
        webbrowser.open(f"http://{host}:{port}")
    uvicorn.run(create_app(project=project, models_config=models_config), host=host, port=port)


def api(
    project: Path | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    models_config: Path | None = None,
) -> None:
    """Start only the API; dataset paths refer to this machine."""
    import uvicorn

    from annodesk.app import create_app

    uvicorn.run(
        create_app(mode="api", project=project, models_config=models_config), host=host, port=port
    )


def ui(api_url: str, host: str = "127.0.0.1", port: int = 8080) -> None:
    """Host bundled UI pointing at a separately deployed API."""
    import uvicorn

    from annodesk.app import create_app

    uvicorn.run(create_app(mode="ui", api_url=api_url), host=host, port=port)


def doctor() -> None:
    """Report installed optional dependencies without importing the models."""
    print(
        json.dumps(
            {name: bool(importlib.util.find_spec(name)) for name in ["torch", "ultralytics"]}
        )
    )


def build_ui() -> None:
    """Install frontend dependencies and build bundled assets (requires Node/npm)."""
    root = Path(__file__).resolve().parents[2]
    frontend = root / "frontend"
    if not (frontend / "package.json").exists():
        raise SystemExit("Frontend source is not available in this installation.")
    for args in (["npm", "ci"], ["npm", "run", "build"]):
        subprocess.run(args, cwd=frontend, check=True)


def models(
    action: Annotated[Literal["list"], tyro.conf.Positional] = "list",
    models_config: Path | None = None,
) -> None:
    """List configured local models and resolution errors. Never download files."""
    from annodesk.models import ModelRegistry

    ModelRegistry(models_config).print_json()


def segment(project: Path, model: str = "", models_config: Path | None = None) -> None:
    """Convert existing YOLO boxes to masks locally, without HTTP or a UI.

    Existing masks and locked/excluded objects are skipped. Run again to continue.
    Labels are written to labels_seg; original detection boxes remain in labels.
    """
    from annodesk.batch import segment_dataset
    from annodesk.models import ModelRegistry

    try:
        report = segment_dataset(project, model, ModelRegistry(models_config))
    except ValueError as error:
        raise SystemExit(str(error)) from error
    print(json.dumps(report, indent=2))
    if report["failed"]:
        raise SystemExit(1)


def docs(output: Path | None = None) -> None:
    """Read the bundled user guide or export it to a new Markdown file."""
    from importlib.resources import files

    resource = files("annodesk").joinpath("docs/user-guide.md")
    source = Path(__file__).resolve().parents[2] / "docs/user-guide.md"
    content = (
        resource.read_text(encoding="utf-8")
        if resource.is_file()
        else source.read_text(encoding="utf-8")
    )
    if output is None:
        print(content, end="")
    else:
        try:
            with output.expanduser().open("x", encoding="utf-8") as stream:
                stream.write(content)
        except FileExistsError as error:
            raise SystemExit(f"File already exists; choose another output: {output}") from error
        print(output.expanduser().resolve())


def main() -> None:
    tyro.extras.subcommand_cli_from_dict(
        {
            "serve": serve,
            "api": api,
            "ui": ui,
            "doctor": doctor,
            "docs": docs,
            "build-ui": build_ui,
            "models": models,
            "segment": segment,
        }
    )
