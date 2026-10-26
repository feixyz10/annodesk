"""Stateless, read-only mask previews and revision-checked explicit application."""

import base64
import io
import math

import numpy as np
from PIL import Image
from pydantic import BaseModel, Field

from annodesk.inference import SegmentRequest
from annodesk.masks import contours, decode_mask, encode_mask
from annodesk.storage import RevisionConflict


class CandidateRequest(SegmentRequest):
    expected_revision: int = Field(ge=0)
    project_id: str
    multimask_output: bool = True


class CandidateApply(BaseModel):
    project_id: str
    instance_id: str
    revision: int = Field(ge=0)
    image_stamp: str
    model: str
    mask: dict


def image_stamp(project, image_id):
    stat = project.image_path(image_id).stat()
    # Preserve nanosecond precision across JavaScript JSON round trips.
    return f"{stat.st_mtime_ns}:{stat.st_size}"


def target(annotation, instance_id):
    obj = next((o for o in annotation.instances if o.id == instance_id), None)
    if annotation.excluded:
        raise ValueError("Image is excluded")
    if obj is None:
        raise ValueError("Select an object with points or a box prompt")
    if obj.locked:
        raise ValueError("Object is locked")
    if obj.hidden:
        raise ValueError("Unhide this object before generating candidates")
    if not (obj.box or obj.prompt_box or obj.points):
        raise ValueError("Select an object with points or a box prompt")
    return obj


def overlay(mask, color):
    rgba = np.zeros((*mask.shape, 4), dtype=np.uint8)
    rgba[:, :, :3] = [int(color[i : i + 2], 16) for i in (1, 3, 5)]
    rgba[:, :, 3] = mask * 110
    output = io.BytesIO()
    Image.fromarray(rgba).save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def preview_candidates(project, image_id, body, adapter):
    if body.operation != "segmentation" or body.text:
        raise ValueError("Mask candidates require a point/box segmentation model, not text")
    with project.lock:
        if body.project_id != project.metadata["id"]:
            raise RevisionConflict("Project changed; generate candidates again")
        annotation = project.annotation(image_id, materialize=False)
        if annotation.revision != body.expected_revision:
            raise RevisionConflict("Annotation changed; generate candidates again")
        obj = target(annotation, body.instance_id)
        width, height = project.image_size(image_id)
        stamp = image_stamp(project, image_id)
        color = next(
            (c["color"] for c in project.metadata["classes"] if c["id"] == obj.class_id), "#657286"
        )
    if body.multimask_output:
        if not callable(getattr(adapter, "predict_candidates", None)):
            raise ValueError("This model adapter does not support mask candidates")
        predictions = adapter.predict_candidates(
            project.image_path(image_id), body.model, obj.prompt_box or obj.box, obj.points
        )
    else:
        predictions = [
            (mask, None)
            for mask in adapter.predict(
                project.image_path(image_id), body.model, obj.prompt_box or obj.box, obj.points, ""
            )[:1]
        ]
    valid = []
    for mask, score in predictions:
        if mask.shape != (height, width):
            raise ValueError("Model mask size does not match the original image")
        binary = (mask != 0).astype(np.uint8)
        if not binary.any():
            continue
        score = float(score) if score is not None and math.isfinite(float(score)) else None
        valid.append((binary, score))
    if not valid:
        raise ValueError("No mask returned; existing annotations were preserved")
    valid.sort(
        key=lambda item: (item[1] is not None, item[1] if item[1] is not None else 0), reverse=True
    )
    with project.lock:
        if (
            image_stamp(project, image_id) != stamp
            or project.annotation(image_id, materialize=False).revision != annotation.revision
        ):
            raise RevisionConflict("Image or annotation changed; generate candidates again")
    return {
        "project_id": project.metadata["id"],
        "image_id": image_id,
        "instance_id": obj.id,
        "revision": annotation.revision,
        "image_stamp": stamp,
        "model": body.model,
        "items": [
            {
                "mask": encode_mask(mask),
                "polygons": contours(mask),
                "quality": score,
                "overlay": overlay(mask, color),
            }
            for mask, score in valid[:3]
        ],
    }


def apply_candidate(project, image_id, body):
    with project.lock:
        if project.metadata["id"] != body.project_id:
            raise RevisionConflict("Project changed; generate candidates again")
        annotation = project.annotation(image_id)
        if (
            annotation.revision != body.revision
            or image_stamp(project, image_id) != body.image_stamp
        ):
            raise RevisionConflict("Image or annotation changed; generate candidates again")
        obj = target(annotation, body.instance_id)
        width, height = project.image_size(image_id)
        if body.mask.get("size") != [height, width] or not isinstance(body.mask.get("counts"), str):
            raise ValueError("Candidate mask size does not match the image")
        try:
            binary = decode_mask(body.mask)
        except (ValueError, TypeError, OverflowError) as error:
            raise ValueError("Invalid candidate mask") from error
        if binary.shape != (height, width) or not binary.any():
            raise ValueError("Candidate mask is empty or has invalid dimensions")
        obj.mask, obj.polygons, obj.source = encode_mask(binary), contours(binary), body.model
        annotation.segmentation_review = "pending"
        annotation.explicit_empty["segmentation"] = False
        if image_stamp(project, image_id) != body.image_stamp:
            raise RevisionConflict("Image changed; generate candidates again")
        return project.save(image_id, annotation)
