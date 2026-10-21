"""Typed console commands. Heavy inference imports are intentionally lazy."""

import importlib.util
import json
import subprocess
import webbrowser
from pathlib import Path

import tyro


def serve(
    project: Path | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    open: bool = False,
) -> None:
    """Start the annotation API and bundled workbench."""
    import uvicorn

    from annodesk.app import create_app

    if open:
        webbrowser.open(f"http://{host}:{port}")
    uvicorn.run(create_app(project=project), host=host, port=port)


def api(project: Path | None = None, host: str = "127.0.0.1", port: int = 8765) -> None:
    """Start only the API; dataset paths refer to this machine."""
    import uvicorn

    from annodesk.app import create_app

    uvicorn.run(create_app(mode="api", project=project), host=host, port=port)


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


def main() -> None:
    tyro.extras.subcommand_cli_from_dict(
        {"serve": serve, "api": api, "ui": ui, "doctor": doctor, "build-ui": build_ui}
    )
