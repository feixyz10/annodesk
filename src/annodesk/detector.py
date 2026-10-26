"""Offline Ultralytics detection adapter and isolated CPU class inspection."""

import multiprocessing as mp
import signal
from pathlib import Path

from annodesk.classes import class_names, read_classes
from annodesk.images import inference_image
from annodesk.models import ModelConfig, ModelRegistry
from annodesk.offline import offline_inference


class DetectionAdapter:
    def __init__(self, registry, device="cpu"):
        self.registry, self.device = registry, device
        self.model = None
        self.names = None
        self.key = None

    def load(self, model_id):
        self.registry.entry(model_id, "detection")
        weights = self.registry.weights(model_id)
        sidecar = self.registry.classes_path(model_id)
        stamp = weights.stat()
        side_stamp = (
            (sidecar.stat().st_mtime_ns, sidecar.stat().st_size)
            if sidecar and sidecar.exists()
            else None
        )
        key = (
            str(weights),
            stamp.st_mtime_ns,
            stamp.st_size,
            str(sidecar),
            side_stamp,
            self.device,
        )
        if key == self.key:
            return self.names
        with offline_inference():
            try:
                import torch
                from ultralytics import YOLO
            except ImportError as error:
                raise ValueError(
                    "Inference dependencies are missing. Run uv sync or reinstall AnnoDesk with its dependencies."
                ) from error
            model = YOLO(str(weights), task="detect")
            if model.task != "detect":
                raise ValueError("The checkpoint is not an object detection model")
            model.to(torch.device(self.device or "cpu"))
            head = model.model.model[-1]
            nc = int(head.nc)
            raw = getattr(model.model, "names", None)
            names = class_names(raw) if raw else None
            if names and all(name in (str(i), f"class_{i}") for i, name in names.items()):
                names = None
            supplied = read_classes(sidecar) if sidecar else None
            if names and supplied and names != supplied:
                raise ValueError("Checkpoint classes and classes_file differ")
            names = supplied or names
            if not names or len(names) != nc:
                raise ValueError(
                    "A reliable class table matching model nc is required; configure classes_file"
                )
            self.model, self.names, self.key = model, names, key
            return names

    def detect(self, path: Path, body):
        self.load(body.model)
        with offline_inference():
            results = self.model.predict(
                inference_image(path),
                device=self.model.device,
                conf=body.confidence,
                iou=body.iou,
                imgsz=body.imgsz,
                max_det=body.max_det,
                classes=body.model_classes,
                save=False,
                verbose=False,
            )
            return [
                {"box": box, "class_index": int(index), "confidence": float(conf)}
                for result in results
                if result.boxes is not None
                for box, index, conf in zip(
                    result.boxes.xyxy.cpu().tolist(),
                    result.boxes.cls.cpu().tolist(),
                    result.boxes.conf.cpu().tolist(),
                    strict=True,
                )
            ]


def _inspect(connection, path, config, model_id):
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        registry = ModelRegistry.__new__(ModelRegistry)
        registry.path, registry.config = Path(path), ModelConfig.model_validate(config)
        connection.send({"names": DetectionAdapter(registry).load(model_id)})
    except Exception as error:
        connection.send({"error": str(error)})
    finally:
        connection.close()


def inspect_classes(registry, model_id):
    context = mp.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(
        target=_inspect, args=(child, str(registry.path), registry.config.model_dump(), model_id)
    )
    process.start()
    child.close()
    try:
        if not parent.poll(180):
            raise ValueError("Model class inspection timed out")
        result = parent.recv()
        if "error" in result:
            raise ValueError(result["error"])
        return class_names(result["names"])
    except EOFError as error:
        raise ValueError("Model class inspection exited without a result") from error
    finally:
        parent.close()
        process.join(timeout=1)
        if process.is_alive():
            process.terminate()
            process.join()
