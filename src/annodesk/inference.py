"""Optional real SAM inference and revision-aware annotation replacement."""

import importlib.util
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from pydantic import BaseModel

from annodesk.devices import DeviceType
from annodesk.domain import Annotation, Instance
from annodesk.masks import contours, encode_mask
from annodesk.models import ModelRegistry
from annodesk.offline import offline_inference
from annodesk.storage import Project


class SegmentRequest(BaseModel):
    model: str = ""
    instance_id: str | None = None
    text: str = ""
    class_id: str | None = None
    device_type: DeviceType = "auto"
    devices: str = "auto"
    num_workers: str | int = "auto"


class UltralyticsAdapter:
    def __init__(self, registry: ModelRegistry | None = None, device: str = "", events=None):
        self.events = events
        self.device = device
        self.registry = registry or ModelRegistry()
        self.predictor = None
        self.key = None
        self.image_key = None

    def predict(self, path: Path, model: str, box, points, text: str):
        entry = self.registry.entry(model)
        weights = self.registry.weights(model)
        if text and entry.backend != "sam3":
            raise ValueError("Text prompts require a SAM 3 model")
        try:
            with offline_inference():
                return self._predict(path, weights, entry.backend, box, points, text)
        except (RuntimeError, ImportError, OSError) as error:
            raise ValueError(f"Local model {entry.id} failed: {error}") from error

    def load(self, model: str):
        entry = self.registry.entry(model)
        with offline_inference():
            self._load(self.registry.weights(model), entry.backend, False)

    def _load(self, weights, backend, text):
        if importlib.util.find_spec("ultralytics") is None:
            raise ValueError("Install inference support with: uv sync --extra inference")
        key = (str(weights), weights.stat().st_mtime_ns, backend, bool(text))
        if self.key != key:
            import torch

            if text:
                from ultralytics.models.sam import SAM3SemanticPredictor

                cls = SAM3SemanticPredictor
            else:
                from ultralytics.models.sam import Predictor, SAM2Predictor

                if backend == "sam3":
                    from ultralytics.models.sam import SAM3Predictor

                    cls = SAM3Predictor
                else:
                    cls = SAM2Predictor if backend == "sam2" else Predictor
            if self.device == "cpu":
                import os

                torch.set_num_threads(max(1, int(os.environ.get("OMP_NUM_THREADS", "1"))))
            self.predictor = None
            self.predictor = cls(
                overrides={
                    "model": str(weights),
                    "task": "segment",
                    "mode": "predict",
                    "save": False,
                    "verbose": False,
                    "device": torch.device(self.device) if self.device else "",
                }
            )
            self.predictor.setup_model(verbose=False)
            self.key, self.image_key = key, None
            if self.events:
                self.events.emit(
                    "INFO",
                    f"Model ready: {weights}; device={self.predictor.device}",
                    event_type="model_ready",
                )

    def _predict(self, path, weights, backend, box, points, text):
        self._load(weights, backend, text)
        image_key = (str(path), path.stat().st_mtime_ns, path.stat().st_size)
        if image_key != self.image_key:
            self.predictor.set_image(str(path))
            self.image_key = image_key
        prompts = (
            {"text": [text]}
            if text
            else {
                "bboxes": [box] if box else None,
                "points": [[p.x, p.y] for p in points] or None,
                "labels": [int(p.positive) for p in points] or None,
            }
        )
        results = self.predictor(**prompts)
        return [
            mask.cpu().numpy().astype(np.uint8)
            for result in results
            if result.masks is not None
            for mask in result.masks.data
        ]


class SegmentationService:
    def __init__(self, project: Project, adapter=None):
        self.project = project
        self.adapter = adapter or UltralyticsAdapter()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="annodesk-inference")
        self.active = False

    def close(self):
        self.executor.shutdown(wait=True, cancel_futures=True)

    def process(self, image_id: str, body: SegmentRequest):
        if isinstance(self.adapter, UltralyticsAdapter):
            body = body.model_copy(update={"model": self.adapter.registry.entry(body.model).id})
        self.active = True
        try:
            return self._process(image_id, body)
        finally:
            self.active = False

    def _process(self, image_id: str, body: SegmentRequest):
        with self.project.lock:
            annotation = self.project.annotation(image_id)
        computed = compute_annotation(
            self.project.image_path(image_id),
            self.project.image_size(image_id),
            annotation,
            body,
            self.adapter,
        )
        return self.project.save(image_id, computed)


def compute_annotation(
    path: Path, size: tuple[int, int], annotation: Annotation, body: SegmentRequest, adapter
) -> Annotation:
    """Pure inference: workers receive snapshots and never construct or write a Project."""
    if annotation.excluded:
        raise ValueError("Image is excluded")
    targets = (
        [o for o in annotation.instances if o.id == body.instance_id]
        if body.instance_id
        else [
            o
            for o in annotation.instances
            if o.box and not o.mask and not o.polygons and not o.locked
        ]
    )
    if body.text:
        if body.class_id is None:
            raise ValueError("Choose a class before text segmentation")
        targets = [Instance(class_id=body.class_id)]
    if not targets or (
        not body.text and any(not (o.box or o.prompt_box or o.points) for o in targets)
    ):
        raise ValueError("Select an object with points or a box prompt")
    for target in targets:
        if target.locked:
            raise ValueError("Object is locked")
        masks = adapter.predict(
            path, body.model, target.prompt_box or target.box, target.points, body.text
        )
        if not masks:
            raise ValueError("No mask returned; existing annotations were preserved")
        for i, mask in enumerate(masks):
            if mask.shape != size[::-1]:
                raise ValueError("Model mask size does not match the original image")
            obj = target.model_copy(deep=True) if i == 0 else Instance(class_id=target.class_id)
            obj.mask, obj.polygons, obj.source = encode_mask(mask), contours(mask), body.model
            if body.text:
                annotation.instances.append(obj)
            else:
                index = next(j for j, o in enumerate(annotation.instances) if o.id == target.id)
                annotation.instances[index] = obj
                break
    if annotation.segmentation_review == "ok":
        annotation.segmentation_review = "pending"
    return annotation
