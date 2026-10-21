"""Optional real SAM inference and revision-aware annotation replacement."""

import importlib.util
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from platformdirs import user_cache_path
from pydantic import BaseModel

from annodesk.domain import Instance
from annodesk.masks import contours, encode_mask
from annodesk.storage import Project


class SegmentRequest(BaseModel):
    model: str = "sam2.1_s.pt"
    instance_id: str | None = None
    text: str = ""
    class_id: str | None = None


class UltralyticsAdapter:
    def __init__(self):
        self.predictor = None
        self.key = None
        self.image_key = None

    def predict(self, path: Path, model: str, box, points, text: str):
        if importlib.util.find_spec("ultralytics") is None:
            raise ValueError("Install inference support with: uv sync --extra inference")
        weights = Path(model).expanduser()
        if not weights.is_file():
            weights = user_cache_path("annodesk") / "models" / Path(model).name
        if not weights.is_file():
            raise ValueError(
                f"Model weights not found: {model}. Use annodesk models fetch or provide a local path."
            )
        key = (str(weights.resolve()), bool(text))
        if self.key != key:
            if text:
                if "sam3" not in weights.name:
                    raise ValueError("Text prompts require a SAM 3 model")
                from ultralytics.models.sam import SAM3SemanticPredictor

                cls = SAM3SemanticPredictor
            else:
                from ultralytics.models.sam import Predictor, SAM2Predictor

                if "sam3" in weights.name:
                    from ultralytics.models.sam import SAM3Predictor

                    cls = SAM3Predictor
                else:
                    cls = SAM2Predictor if "sam2" in weights.name else Predictor
            self.predictor = None
            self.predictor = cls(
                overrides={
                    "model": str(weights),
                    "task": "segment",
                    "mode": "predict",
                    "save": False,
                    "verbose": False,
                }
            )
            self.key, self.image_key = key, None
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
        self.jobs: dict[str, dict] = {}
        self.job_lock = threading.RLock()

    def close(self):
        self.executor.shutdown(wait=False, cancel_futures=True)

    def process(self, image_id: str, body: SegmentRequest):
        with self.project.lock:
            annotation = self.project.annotation(image_id)
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
            masks = self.adapter.predict(
                self.project.image_path(image_id),
                body.model,
                target.prompt_box or target.box,
                target.points,
                body.text,
            )
            if not masks:
                raise ValueError("No mask returned; existing annotations were preserved")
            for i, mask in enumerate(masks):
                if mask.shape != self.project.image_size(image_id)[::-1]:
                    raise ValueError("Model mask size does not match the original image")
                obj = target.model_copy(deep=True) if i == 0 else Instance(class_id=target.class_id)
                obj.mask = encode_mask(mask)
                obj.polygons = contours(mask)
                obj.source = body.model
                if body.text:
                    annotation.instances.append(obj)
                else:
                    index = next(j for j, o in enumerate(annotation.instances) if o.id == target.id)
                    annotation.instances[index] = obj
                    break
        if annotation.segmentation_review == "ok":
            annotation.segmentation_review = "pending"
        return self.project.save(image_id, annotation)
