"""Optional real SAM inference and revision-aware annotation replacement."""

import importlib.util
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np
from pydantic import BaseModel, Field

from annodesk.devices import DeviceType
from annodesk.domain import Annotation, Instance
from annodesk.images import inference_image
from annodesk.masks import contours, encode_mask
from annodesk.models import ModelRegistry
from annodesk.offline import offline_inference
from annodesk.storage import Project, RevisionConflict, fingerprint


class SegmentRequest(BaseModel):
    model: str = ""
    operation: Literal["segmentation", "detection", "boxes_from_masks"] = "segmentation"
    confidence: float = Field(default=0.25, ge=0, le=1)
    iou: float = Field(default=0.7, ge=0, le=1)
    imgsz: int = Field(default=640, ge=32, le=8192)
    max_det: int = Field(default=300, ge=1, le=10000)
    model_classes: list[int] | None = None
    allow_new_classes: bool = False
    write_policy: Literal["fill_empty", "append"] = "fill_empty"
    recalculate_boxes: bool = False
    review_states: list[Literal["pending", "uncertain", "ok"]] = Field(
        default_factory=lambda: ["pending"], min_length=1
    )
    image_ids: list[str] | None = None
    class_names: dict[int, str] = Field(default_factory=dict)
    class_ids: dict[int, str] = Field(default_factory=dict)
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
        self.detector = None
        self.loaded_id = ""

    def predict(self, path: Path, model: str, box, points, text: str):
        entry = self.registry.entry(model, "segmentation")
        weights = self.registry.weights(model)
        if text and entry.backend != "sam3":
            raise ValueError("Text prompts require a SAM 3 model")
        try:
            with offline_inference():
                result = self._predict(path, weights, entry.backend, box, points, text)
                self.loaded_id = entry.id
                return result
        except (RuntimeError, ImportError, OSError) as error:
            raise ValueError(f"Local model {entry.id} failed: {error}") from error

    def load(self, model: str):
        self.loaded_id = ""
        entry = self.registry.entry(model)
        if entry.task == "detection":
            from annodesk.detector import DetectionAdapter

            if self.detector is None:
                self.detector = DetectionAdapter(self.registry, self.device or "cpu")
            self.detector.registry = self.registry
            self.detector.device = self.device or "cpu"
            previous_key = self.detector.key
            names = self.detector.load(model)
            if self.events and self.detector.key != previous_key:
                self.events.emit(
                    "INFO",
                    f"Detection model ready: {entry.id}; device={self.detector.device}; classes={len(names)}",
                    event_type="model_ready",
                )
            self.predictor, self.key = None, None
            self.loaded_id = entry.id
            return names
        self.detector = None
        with offline_inference():
            self._load(self.registry.weights(model), entry.backend, False)
        self.loaded_id = entry.id

    def detect(self, path, body):
        self.load(body.model)
        if self.detector.names != body.class_names:
            raise ValueError("Model classes changed after the task was planned")
        return self.detector.detect(path, body)

    def _load(self, weights, backend, text):
        if importlib.util.find_spec("ultralytics") is None:
            raise ValueError(
                "Inference dependencies are missing. Run uv sync or reinstall AnnoDesk with its dependencies."
            )
        key = (str(weights), weights.stat().st_mtime_ns, backend, bool(text), self.device)
        if self.key != key or self.predictor is None:
            # Invalidate before construction/imports. Publish a new predictor and
            # its key together only after setup succeeds; failures remain retryable.
            self.predictor, self.key, self.image_key = None, None, None
            self.loaded_id = ""
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
            predictor = cls(
                overrides={
                    "model": str(weights),
                    "task": "segment",
                    "mode": "predict",
                    "save": False,
                    "verbose": False,
                    "device": torch.device(self.device) if self.device else "",
                }
            )
            # Meta checkpoints use different names from Ultralytics' filename dispatcher.
            # Build known official architectures explicitly, keeping the original local path.
            official = {
                "sam2_hiera_tiny.pt": "build_sam2_t",
                "sam2_hiera_small.pt": "build_sam2_s",
                "sam2_hiera_base_plus.pt": "build_sam2_b",
                "sam2_hiera_large.pt": "build_sam2_l",
                "sam2.1_hiera_tiny.pt": "build_sam2_t",
                "sam2.1_hiera_small.pt": "build_sam2_s",
                "sam2.1_hiera_base_plus.pt": "build_sam2_b",
                "sam2.1_hiera_large.pt": "build_sam2_l",
            }
            builder = official.get(weights.name) if backend == "sam2" else None
            if builder:
                from ultralytics.models.sam import build

                predictor.setup_model(model=getattr(build, builder)(str(weights)), verbose=False)
            else:
                predictor.setup_model(verbose=False)
            self.predictor, self.key, self.image_key = predictor, key, None
            if self.events:
                self.events.emit(
                    "INFO",
                    f"Model ready: {weights}; device={self.predictor.device}",
                    event_type="model_ready",
                )

    def predict_candidates(self, path, model, box, points):
        entry = self.registry.entry(model, "segmentation")
        try:
            with offline_inference():
                result = self._predict(
                    path,
                    self.registry.weights(model),
                    entry.backend,
                    box,
                    points,
                    "",
                    candidates=True,
                )
                self.loaded_id = entry.id
                return result
        except (RuntimeError, ImportError, OSError, TypeError) as error:
            raise ValueError(
                f"Local model {entry.id} candidate inference failed: {error}"
            ) from error

    def _predict(self, path, weights, backend, box, points, text, *, candidates=False):
        self._load(weights, backend, text)
        image_key = (str(path), path.stat().st_mtime_ns, path.stat().st_size)
        if image_key != self.image_key:
            self.predictor.set_image(inference_image(path))
            self.image_key = image_key
        prompts = (
            {"text": [text]}
            if text
            else {
                "bboxes": [box] if box else None,
                # All clicks refine one instance. A flat Nx2 array instead
                # describes N independently prompted objects in Ultralytics.
                "points": [[[p.x, p.y] for p in points]] if points else None,
                "labels": [[int(p.positive) for p in points]] if points else None,
            }
        )
        # This is an inference argument, not an Ultralytics config override.
        # Semantic text segmentation is a separate multi-object pipeline.
        results = self.predictor(**prompts, **({} if text else {"multimask_output": candidates}))
        if candidates:
            output = []
            for result in results:
                if result.masks is None:
                    continue
                scores = result.boxes.conf.cpu().tolist() if result.boxes is not None else []
                for index, mask in enumerate(result.masks.data):
                    output.append(
                        (
                            mask.cpu().numpy().astype(np.uint8),
                            scores[index] if index < len(scores) else None,
                        )
                    )
            return output
        return [
            mask.cpu().numpy().astype(np.uint8)
            for result in results
            if result.masks is not None
            for mask in result.masks.data
        ]


@dataclass(frozen=True)
class RequestSnapshot:
    annotation: Annotation
    size: tuple[int, int]
    stamp: tuple[int, int]
    labels: tuple[str, str]


class SegmentationService:
    def __init__(self, project: Project, adapter=None):
        self.project = project
        self.adapter = adapter or UltralyticsAdapter()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="annodesk-inference")
        self.active = False
        self.registry = (
            self.adapter.registry if isinstance(self.adapter, UltralyticsAdapter) else None
        )
        self.device_key = None

    def close(self):
        self.executor.shutdown(wait=True, cancel_futures=True)

    def configure(self, body):
        if isinstance(self.adapter, UltralyticsAdapter) and body.operation != "boxes_from_masks":
            from annodesk.devices import ExecutionOptions, resolve_plan

            key = (body.device_type, body.devices)
            if key != self.device_key:
                plan = resolve_plan(ExecutionOptions(body.device_type, body.devices, "1"))
                self.adapter.device = plan.workers[0]
                self.device_key = key
            self.adapter.registry = self.registry.freeze()
            entry = self.adapter.registry.entry(body.model, body.operation)
            body = body.model_copy(update={"model": entry.id})
        return body

    def warm(self, body):
        self.active = True
        try:
            body = self.configure(body)
            names = self.adapter.load(body.model)
            from annodesk.classes import compatible

            return {
                "model": body.model,
                "loaded": True,
                "device": self.adapter.device,
                "class_names": names,
                "compatibility": compatible(names, self.project.metadata) if names else None,
            }
        finally:
            self.active = False

    def snapshot(self, image_id: str) -> RequestSnapshot:
        from annodesk.execution import file_stamp

        with self.project.lock:
            self.project.ensure_writable()
            annotation = self.project.annotation(image_id).model_copy(deep=True)
            self.project.validate_fingerprints(image_id)
            return RequestSnapshot(
                annotation,
                self.project.image_size(image_id),
                file_stamp(self.project.image_path(image_id)),
                tuple(fingerprint(self.project.label_path(image_id, seg)) for seg in (False, True)),
            )

    def submit(self, image_id: str, body: SegmentRequest):
        # Capture before entering the serial executor, including mutable request fields.
        snapshot = self.snapshot(image_id)
        return self.executor.submit(self.process, image_id, body.model_copy(deep=True), snapshot)

    def validate_snapshot(self, image_id: str, snapshot: RequestSnapshot):
        from annodesk.execution import file_stamp

        self.project.ensure_writable()
        if self.project.annotation(image_id).revision != snapshot.annotation.revision:
            raise RevisionConflict("Annotation changed. Reload before saving.")
        self.project.validate_fingerprints(image_id)
        labels = tuple(fingerprint(self.project.label_path(image_id, seg)) for seg in (False, True))
        if labels != snapshot.labels:
            raise RevisionConflict(
                "YOLO labels changed outside AnnoDesk; reopen or reconcile them."
            )
        if file_stamp(self.project.image_path(image_id)) != snapshot.stamp:
            raise ValueError("Image changed during processing")

    def process(self, image_id: str, body: SegmentRequest, snapshot: RequestSnapshot | None = None):
        snapshot = snapshot or self.snapshot(image_id)
        with self.project.lock:
            self.validate_snapshot(image_id, snapshot)
        self.active = True
        try:
            body = self.configure(body)
            if body.operation == "detection":
                from annodesk.operations import prepare_detection

                body = prepare_detection(self.project, body, self.adapter.load(body.model))
            return self._process(image_id, body, snapshot)
        finally:
            self.active = False

    def candidates(self, image_id, body):
        from annodesk.candidates import preview_candidates

        self.active = True
        try:
            configured = self.configure(body)
            body = body.model_copy(update={"model": configured.model})
            return preview_candidates(self.project, image_id, body, self.adapter)
        finally:
            self.active = False

    def _process(self, image_id: str, body: SegmentRequest, snapshot: RequestSnapshot):
        computed = compute_annotation(
            self.project.image_path(image_id),
            snapshot.size,
            snapshot.annotation.model_copy(deep=True),
            body,
            self.adapter,
        )
        from annodesk.operations import commit_result

        with self.project.lock:
            self.validate_snapshot(image_id, snapshot)
            return commit_result(self.project, image_id, computed, body)


def compute_annotation(
    path: Path, size: tuple[int, int], annotation: Annotation, body: SegmentRequest, adapter
) -> Annotation:
    """Pure inference: workers receive snapshots and never construct or write a Project."""
    if body.operation != "segmentation":
        from annodesk.operations import compute_boxes

        return compute_boxes(path, size, annotation, body, adapter)
    if annotation.excluded:
        raise ValueError("Image is excluded")
    targets = (
        [o for o in annotation.instances if o.id == body.instance_id]
        if body.instance_id
        else [
            o
            for o in annotation.instances
            if (o.box or o.prompt_box or o.points)
            and not o.mask
            and not o.polygons
            and not o.locked
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
        accepted = 0
        for mask in masks:
            if mask.shape != size[::-1]:
                raise ValueError("Model mask size does not match the original image")
            mask = (mask != 0).astype(np.uint8)
            if not mask.any():
                continue
            obj = (
                target.model_copy(deep=True)
                if accepted == 0
                else Instance(class_id=target.class_id)
            )
            obj.mask, obj.polygons, obj.source = encode_mask(mask), contours(mask), body.model
            accepted += 1
            if body.text:
                annotation.instances.append(obj)
            else:
                index = next(j for j, o in enumerate(annotation.instances) if o.id == target.id)
                annotation.instances[index] = obj
                break
        if not accepted:
            raise ValueError("No mask returned; existing annotations were preserved")
    annotation.segmentation_review = "pending"
    annotation.explicit_empty["segmentation"] = False
    return annotation
