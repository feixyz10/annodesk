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


def models(
    action: Annotated[Literal["list", "fetch"], tyro.conf.Positional] = "list",
    name: Annotated[str, tyro.conf.Positional] = "sam2.1_s.pt",
) -> None:
    """List model files or explicitly fetch an Ultralytics model checkpoint."""
    from platformdirs import user_cache_path

    cache = user_cache_path("annodesk") / "models"
    supported = ["sam2.1_s.pt", "mobile_sam.pt", "sam3.pt"]
    if action == "list":
        print(
            json.dumps(
                [
                    {"name": n, "path": str(cache / n), "available": (cache / n).is_file()}
                    for n in supported
                ],
                indent=2,
            )
        )
        return
    if name not in supported:
        raise SystemExit("Unknown model. Use a local checkpoint path in the workbench.")
    if name == "sam3.pt":
        raise SystemExit(
            "SAM 3 weights may require access approval. Place your authorized checkpoint at "
            + str(cache / name)
        )
    if importlib.util.find_spec("ultralytics") is None:
        raise SystemExit("Install the model runtime first: uv sync --extra inference")
    from ultralytics.utils.downloads import attempt_download_asset

    cache.mkdir(parents=True, exist_ok=True)
    result = Path(attempt_download_asset(str(cache / name)))
    if not result.is_file():
        raise SystemExit("Download failed; provide a local checkpoint instead.")
    print(result)


def main() -> None:
    tyro.extras.subcommand_cli_from_dict(
        {
            "serve": serve,
            "api": api,
            "ui": ui,
            "doctor": doctor,
            "build-ui": build_ui,
            "models": models,
        }
    )
