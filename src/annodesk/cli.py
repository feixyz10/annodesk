"""Typed console commands. Heavy inference imports are intentionally lazy."""

import importlib.util
import json
import subprocess
import webbrowser
from pathlib import Path
from typing import Annotated, Literal

import tyro

from annodesk.devices import DeviceType


def serve(
    project: Path | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    open: bool = False,
    models_config: Path | None = None,
    log_dir: Path | None = None,
    log_level: str = "INFO",
) -> None:
    """Start the annotation API and bundled workbench."""
    from annodesk.app import create_app

    if open:
        webbrowser.open(f"http://{host}:{port}")
    _run_server(
        create_app(
            project=project, models_config=models_config, events=_logging(log_dir, log_level)
        ),
        host,
        port,
    )


def api(
    project: Path | None = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    models_config: Path | None = None,
    log_dir: Path | None = None,
    log_level: str = "INFO",
) -> None:
    """Start only the API; dataset paths refer to this machine."""
    from annodesk.app import create_app

    _run_server(
        create_app(
            mode="api",
            project=project,
            models_config=models_config,
            events=_logging(log_dir, log_level),
        ),
        host,
        port,
    )


def ui(
    api_url: str,
    host: str = "127.0.0.1",
    port: int = 8080,
    log_dir: Path | None = None,
    log_level: str = "INFO",
) -> None:
    """Host bundled UI pointing at a separately deployed API."""
    from annodesk.app import create_app

    _run_server(
        create_app(mode="ui", api_url=api_url, events=_logging(log_dir, log_level)), host, port
    )


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
    log_dir: Path | None = None,
    log_level: str = "INFO",
) -> None:
    """List configured local models and resolution errors. Never download files."""
    from annodesk.models import ModelRegistry

    ModelRegistry(models_config).print_json()


def segment(
    project: Path,
    model: str = "",
    models_config: Path | None = None,
    device_type: DeviceType = "auto",
    devices: str = "auto",
    num_workers: str = "auto",
    review_states: tuple[Literal["pending", "uncertain", "ok"], ...] = ("pending",),
    log_dir: Path | None = None,
    log_level: str = "INFO",
) -> None:
    """Convert missing box masks without HTTP. Existing masks/locked/excluded items are skipped."""
    _run_operation(
        project,
        _request(
            model=model,
            device_type=device_type,
            devices=devices,
            num_workers=num_workers,
            review_states=list(review_states),
        ),
        models_config,
        log_dir,
        log_level,
    )


def detect(
    project: Path,
    model: str = "",
    models_config: Path | None = None,
    confidence: float = 0.25,
    iou: float = 0.7,
    imgsz: int = 640,
    max_det: int = 300,
    model_classes: tuple[int, ...] | None = None,
    allow_new_classes: bool = False,
    write_policy: Literal["fill_empty", "append"] = "fill_empty",
    review_states: tuple[Literal["pending", "uncertain", "ok"], ...] = ("pending",),
    device_type: DeviceType = "auto",
    devices: str = "auto",
    num_workers: str = "auto",
    log_dir: Path | None = None,
    log_level: str = "INFO",
) -> None:
    """Generate editable detection boxes using a local model and strictly compatible classes."""
    _run_operation(
        project,
        _request(
            operation="detection",
            model=model,
            confidence=confidence,
            iou=iou,
            imgsz=imgsz,
            max_det=max_det,
            model_classes=list(model_classes) if model_classes is not None else None,
            allow_new_classes=allow_new_classes,
            write_policy=write_policy,
            review_states=list(review_states),
            device_type=device_type,
            devices=devices,
            num_workers=num_workers,
        ),
        models_config,
        log_dir,
        log_level,
    )


def boxes_from_masks(
    project: Path,
    recalculate_boxes: bool = False,
    review_states: tuple[Literal["pending", "uncertain", "ok"], ...] = ("pending",),
    log_dir: Path | None = None,
    log_level: str = "INFO",
) -> None:
    """Create explicit boxes on existing masks; CPU geometry only, no model loading."""
    _run_operation(
        project,
        _request(
            operation="boxes_from_masks",
            device_type="cpu",
            recalculate_boxes=recalculate_boxes,
            review_states=list(review_states),
        ),
        None,
        log_dir,
        log_level,
    )


def _request(**options):
    from annodesk.inference import SegmentRequest

    try:
        return SegmentRequest(**options)
    except ValueError as error:
        print(str(error))
        raise SystemExit(2) from error


def _run_operation(project, body, models_config, log_dir, log_level):
    from annodesk.batch import segment_dataset
    from annodesk.models import ModelRegistry

    events = _logging(log_dir, log_level)
    try:
        report = segment_dataset(
            project,
            body.model,
            None if body.operation == "boxes_from_masks" else ModelRegistry(models_config),
            events=events,
            request=body,
        )
    except KeyboardInterrupt as error:
        raise SystemExit(130) from error
    except (ValueError, OSError) as error:
        events.emit("CRITICAL", str(error), event_type="startup_error")
        raise SystemExit(2) from error
    finally:
        events.close()
    if report["status"] == "cancelled":
        raise SystemExit(130)
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


def _logging(log_dir, log_level):
    import sys

    from loguru import logger

    from annodesk.events import EventLog

    logger.remove()
    logger.add(
        sys.stderr,
        level=log_level.upper(),
        diagnose=False,
        backtrace=False,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS ZZ} | {level: <8} | {message}",
    )
    return EventLog(log_dir, log_level, files=True)


def _run_server(app, host, port):
    import logging

    import uvicorn

    class Forward(logging.Handler):
        def emit(self, record):
            if record.name == "uvicorn.access":
                if "/api/v1/logs" not in record.getMessage():
                    app.state.events.emit("DEBUG", record.getMessage(), ui_visible=False)
            else:
                app.state.events.emit(
                    record.levelname,
                    record.getMessage(),
                    ui_visible=record.levelno >= 30,
                    event_type="server",
                    _exception=record.exc_info,
                )

    logging.basicConfig(handlers=[Forward()], level=logging.WARNING, force=True)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        item = logging.getLogger(name)
        item.handlers.clear()
        item.setLevel(logging.DEBUG)
        item.propagate = True
    uvicorn.run(app, host=host, port=port, log_config=None)


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
            "detect": detect,
            "boxes-from-masks": boxes_from_masks,
        }
    )
