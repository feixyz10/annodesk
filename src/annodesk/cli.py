"""Typed console commands. Heavy inference imports are intentionally lazy."""

import importlib.util
import json
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
    api_only: bool = False,
    models_config: Path | None = None,
    log_dir: Path | None = None,
    log_level: str = "INFO",
) -> None:
    """Start the annotation API and bundled workbench.

    Run on the computer that reads/writes the dataset and performs inference.
    On that computer, browse http://127.0.0.1:8765 (default port).
    For a GPU server, bind --host 0.0.0.0 and browse http://SERVER_IP:8765
    from your own computer. No separate ui command is needed in this case.
    Use --api-only to omit the page when hosting it separately with ui.
    Dataset paths always refer to the server; local-dataset remote inference
    is not supported.

    Args:
        project: Dataset or image directory on this backend machine. Omit/None: start without a project; open one later from the workbench.
        host: Address to bind. 127.0.0.1 accepts local connections only; use 0.0.0.0 to accept connections from other computers.
        port: HTTP port for the API and workbench.
        open: Open the workbench in a browser on the computer running this command. When serving remotely, open http://SERVER_IP:PORT in your own browser instead.
        api_only: Start only the backend API, without a workbench page. Dataset reads/writes and inference still run on this computer. Use ui elsewhere for the page; cannot combine with --open.
        models_config: Model configuration JSON. Omit/None: check ANNODESK_MODELS_CONFIG, then ./models.json, then the repository or bundled preset configuration. Model weights are never downloaded.
        log_dir: Directory for session log files. Omit/None: use ~/.cache/annodesk, including on macOS. Relative paths use the current working directory.
        log_level: Minimum file/terminal log level: TRACE, DEBUG, INFO, SUCCESS, WARNING, ERROR or CRITICAL. Does not change the UI filter.
    """
    from annodesk.app import create_app

    if api_only and open:
        raise SystemExit("--open cannot be combined with --api-only: no workbench page is served.")
    if open:
        webbrowser.open(f"http://{host}:{port}")
    _run_server(
        create_app(
            mode="api" if api_only else "serve",
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
    """Host bundled UI pointing at a separately deployed API.

    Run on the computer hosting the web page, e.g. your laptop.
    With the default host/port, browse http://127.0.0.1:8080 on that computer.
    The browser calls --api-url directly. Dataset/model paths, saves and
    inference all belong to the API computer; ui does not open local datasets
    or upload them for remote inference. Separate hosting is optional; serve
    already provides both the page and API from one computer.

    Args:
        api_url: API server base URL, e.g. http://gpu-host:8765, without /api/v1. It must be reachable from the user's browser, not just this computer.
        host: Address to bind for serving the workbench. Use 0.0.0.0 to make the page accessible from other computers; 127.0.0.1 is local only.
        port: HTTP port for the workbench page.
        log_dir: Directory for this UI process's session logs. Omit/None: use ~/.cache/annodesk. Backend logs remain on the API computer.
        log_level: Minimum file/terminal log level: TRACE, DEBUG, INFO, SUCCESS, WARNING, ERROR or CRITICAL. Does not change the UI filter.
    """
    from annodesk.app import create_app

    _run_server(
        create_app(mode="ui", api_url=api_url, events=_logging(log_dir, log_level)), host, port
    )


def doctor() -> None:
    """Check whether inference dependencies are installed."""
    print(
        json.dumps(
            {name: bool(importlib.util.find_spec(name)) for name in ["torch", "ultralytics"]}
        )
    )


def models(
    action: Annotated[Literal["list"], tyro.conf.Positional] = "list",
    models_config: Path | None = None,
) -> None:
    """List configured local models and resolution errors. Never download files.

    Args:
        action: Read-only listing of model IDs, local paths and availability. The only action is list; no model runtime is loaded.
        models_config: Model configuration JSON. Omit/None: check ANNODESK_MODELS_CONFIG, then ./models.json, then the repository or bundled preset configuration. This command creates no log files.
    """
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
    """Convert missing box masks without HTTP. Existing masks/locked/excluded items are skipped.

    Args:
        project: Dataset directory to process on this machine. Close any AnnoDesk service writing this project before running the command.
        model: Segmentation model ID from models.json, not a weight filename. Omit/empty: use segmentation.default_model from the selected config.
        models_config: Model configuration JSON. Omit/None: check ANNODESK_MODELS_CONFIG, then ./models.json, then the repository or bundled preset configuration. Model weights are never downloaded.
        device_type: Compute backend. auto selects CUDA, then MPS, then CPU. An explicitly selected unavailable backend fails instead of falling back.
        devices: CUDA logical indices, e.g. 0,1, after CUDA_VISIBLE_DEVICES. auto uses all visible CUDA devices. CPU/MPS accept auto only.
        num_workers: Positive worker count or auto: one worker per selected CUDA device, otherwise one. Workers are spread across selected devices; multiple workers on one device each load their own model.
        review_states: Segmentation review states to include, space-separated: pending (Not reviewed), uncertain (Needs review), ok (Approved). Excluded images and existing masks are always skipped.
        log_dir: Directory for session log files. Omit/None: use ~/.cache/annodesk. Relative paths use the current working directory.
        log_level: Minimum file/terminal log level: TRACE, DEBUG, INFO, SUCCESS, WARNING, ERROR or CRITICAL.
    """
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
    """Generate editable detection boxes using a local model and strictly compatible classes.

    Args:
        project: Dataset directory to process on this machine. Close any AnnoDesk service writing this project before running the command.
        model: Detection model ID from models.json, not a weight filename. Omit/empty: use detection.default_model from the selected config.
        models_config: Model configuration JSON. Omit/None: check ANNODESK_MODELS_CONFIG, then ./models.json, then the repository or bundled preset configuration. Model weights are never downloaded.
        confidence: Minimum detection confidence, from 0 to 1.
        iou: Non-maximum suppression IoU threshold, from 0 to 1. This is separate from the fixed duplicate check used by append.
        imgsz: Inference image size in pixels; does not resize saved source images.
        max_det: Maximum detections per image.
        model_classes: Model class IDs to consider, space-separated, e.g. 0 15. Omit/None: consider all model classes, subject to project compatibility.
        allow_new_classes: Add model classes absent from the project only when retained detections are saved. IDs/names must remain compatible. Disabled: discard detections of classes outside the project.
        write_policy: fill_empty processes only images without annotation instances. append preserves existing annotations and skips duplicate same-class boxes. Neither policy replaces human annotations.
        review_states: Detection review states to include, space-separated: pending (Not reviewed), uncertain (Needs review), ok (Approved). Excluded images are always skipped.
        device_type: Compute backend. auto selects CUDA, then MPS, then CPU. An explicitly selected unavailable backend fails instead of falling back.
        devices: CUDA logical indices, e.g. 0,1, after CUDA_VISIBLE_DEVICES. auto uses all visible CUDA devices. CPU/MPS accept auto only.
        num_workers: Positive worker count or auto: one worker per selected CUDA device, otherwise one. Workers are spread across selected devices; multiple workers on one device each load their own model.
        log_dir: Directory for session log files. Omit/None: use ~/.cache/annodesk. Relative paths use the current working directory.
        log_level: Minimum file/terminal log level: TRACE, DEBUG, INFO, SUCCESS, WARNING, ERROR or CRITICAL.
    """
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
    """Create explicit boxes on existing masks; CPU geometry only, no model loading.

    Args:
        project: Dataset directory to process on this machine. Close any AnnoDesk service writing this project before running the command.
        recalculate_boxes: Replace existing unlocked boxes using mask bounds. Disabled: create only missing boxes. Masks/classes are preserved; locked instances are always skipped.
        review_states: Detection review states to include, space-separated: pending (Not reviewed), uncertain (Needs review), ok (Approved). Excluded images are always skipped.
        log_dir: Directory for session log files. Omit/None: use ~/.cache/annodesk. Relative paths use the current working directory.
        log_level: Minimum file/terminal log level: TRACE, DEBUG, INFO, SUCCESS, WARNING, ERROR or CRITICAL.
    """
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
    """Read the user guide or save a Markdown copy.

    Args:
        output: Destination Markdown file. Omit/None: print the installed guide to the terminal. An existing file is never overwritten.
    """
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
            "segment": segment,
            "detect": detect,
            "boxes-from-masks": boxes_from_masks,
            "ui": ui,
            "models": models,
            "doctor": doctor,
            "docs": docs,
        },
        description=(
            "Annotate images with boxes and masks. Start the workbench with serve; "
            "run segment, detect or boxes-from-masks for headless processing. "
            "Use serve --api-only with ui for separate web hosting; models/doctor/docs help with setup."
        ),
    )
