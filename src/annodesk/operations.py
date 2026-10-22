"""Box assistance: pure worker geometry and strict parent-only class creation."""

import math

import numpy as np

from annodesk.classes import class_names, compatible
from annodesk.colors import choose_color
from annodesk.domain import Instance, uid
from annodesk.masks import decode_mask


def target_task(body):
    return "segmentation" if body.operation == "segmentation" else "detection"


def eligible(annotation, body):
    if (
        annotation.excluded
        or getattr(annotation, target_task(body) + "_review") not in body.review_states
    ):
        return False
    if body.operation == "detection":
        return body.write_policy == "append" or not annotation.instances
    if body.operation == "boxes_from_masks":
        return any(
            not o.locked and (o.mask or o.polygons) and (not o.box or body.recalculate_boxes)
            for o in annotation.instances
        )
    return any(
        o.box and not o.mask and not o.polygons and not o.locked for o in annotation.instances
    )


def prepare_detection(project, body, names):
    names = class_names(names)
    with project.lock:
        compatible(names, project.metadata)
        enabled = set(body.model_classes) if body.model_classes is not None else names.keys()
        existing = {c["index"] for c in project.metadata["classes"]}
        if not body.allow_new_classes and not (enabled & existing):
            raise ValueError(
                "No model classes are accepted; enable new classes or define compatible project classes"
            )
        if body.model_classes is not None and (
            not body.model_classes or not set(body.model_classes) <= names.keys()
        ):
            raise ValueError("Selected model classes are invalid")
        return body.model_copy(
            update={
                "class_names": names,
                "class_ids": {c["index"]: c["id"] for c in project.metadata["classes"]},
            }
        )


def mask_box(obj, size):
    width, height = size
    if obj.mask:
        mask = decode_mask(obj.mask)
        if mask.shape != (height, width):
            raise ValueError("Mask size differs from the image")
        ys, xs = np.nonzero(mask)
        if not len(xs):
            return None
        box = [float(xs.min()), float(ys.min()), float(xs.max() + 1), float(ys.max() + 1)]
    elif obj.polygons:
        points = [point for polygon in obj.polygons for point in polygon]
        box = [
            min(p[0] for p in points),
            min(p[1] for p in points),
            max(p[0] for p in points),
            max(p[1] for p in points),
        ]
    else:
        return None
    return clip_box(box, size)


def clip_box(box, size):
    if len(box) != 4 or not all(math.isfinite(v) for v in box):
        raise ValueError("Invalid predicted box coordinates")
    width, height = size
    x1, y1, x2, y2 = box
    box = [
        max(0.0, min(width, x1)),
        max(0.0, min(height, y1)),
        max(0.0, min(width, x2)),
        max(0.0, min(height, y2)),
    ]
    return box if box[2] > box[0] and box[3] > box[1] else None


def overlap(a, b):
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0, min(a[3], b[3]) - max(a[1], b[1])
    )
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union if union else 0


def compute_boxes(path, size, annotation, body, adapter):
    if annotation.excluded:
        raise ValueError("Image is excluded")
    annotation.operation_stats = {
        "boxes_added": 0,
        "boxes_updated": 0,
        "detections_discarded": 0,
        "duplicates_skipped": 0,
        "empty_masks": 0,
    }
    changed = False
    if body.operation == "boxes_from_masks":
        targets = [
            o for o in annotation.instances if (not body.instance_id or o.id == body.instance_id)
        ]
        if body.instance_id and not targets:
            raise ValueError("Unknown selected instance")
        for obj in targets:
            if (
                obj.locked
                or (obj.box and not body.recalculate_boxes)
                or not (obj.mask or obj.polygons)
            ):
                continue
            box = mask_box(obj, size)
            if box is None:
                annotation.operation_stats["empty_masks"] += 1
                continue
            if box != obj.box:
                annotation.operation_stats["boxes_updated" if obj.box else "boxes_added"] += 1
                obj.box, obj.box_source = box, "mask"
                changed = True
    else:
        if body.write_policy == "fill_empty" and annotation.instances:
            raise ValueError("Image already contains annotations; use Append explicitly")
        for prediction in adapter.detect(path, body):
            index, confidence = prediction["class_index"], prediction["confidence"]
            if (
                index not in body.class_names
                or not math.isfinite(confidence)
                or not 0 <= confidence <= 1
            ):
                raise ValueError("Detector returned an invalid class ID or confidence")
            box = clip_box(prediction["box"], size)
            if (
                box is None
                or confidence < body.confidence
                or (body.model_classes is not None and index not in body.model_classes)
            ):
                continue
            if index not in body.class_ids and not body.allow_new_classes:
                annotation.operation_stats["detections_discarded"] += 1
                continue
            target_id = body.class_ids.get(index)
            duplicate = any(
                (
                    o.class_id == target_id
                    if target_id
                    else o.model_class_index == index and o.source == f"det:{body.model}"
                )
                and (existing := (o.box or mask_box(o, size))) is not None
                and overlap(box, existing) >= 0.7
                for o in annotation.instances
            )
            if duplicate:
                annotation.operation_stats["duplicates_skipped"] += 1
                continue
            annotation.instances.append(
                Instance(
                    class_id=target_id,
                    box=box,
                    source=f"det:{body.model}",
                    box_source=f"det:{body.model}",
                    model_class_index=index,
                    confidence=confidence,
                )
            )
            annotation.operation_stats["boxes_added"] += 1
            changed = True
    if changed:
        annotation.detection_review = "pending"
        annotation.explicit_empty["detection"] = False
    return annotation


def commit_result(project, image_id, annotation, body):
    with project.lock:
        additions = []
        if body.operation == "detection":
            compatible(body.class_names, project.metadata)
            current = {c["index"]: c for c in project.metadata["classes"]}
            old_ids = {o.id for o in project.annotation(image_id).instances}
            for obj in annotation.instances:
                if (
                    obj.id in old_ids
                    or obj.source != f"det:{body.model}"
                    or obj.model_class_index is None
                ):
                    continue
                index = obj.model_class_index
                if index not in current:
                    if not body.allow_new_classes:
                        raise ValueError("New class creation is disabled")
                    category = {
                        "id": uid(),
                        "index": index,
                        "name": body.class_names[index],
                        "color": choose_color([*current.values()]),
                    }
                    current[index] = category
                    additions.append(category)
                obj.class_id = current[index]["id"]
        annotation.operation_stats["classes_added"] = len(additions)
        return project.save(image_id, annotation, new_classes=additions)


def preview(project, body):
    ids = (
        list(dict.fromkeys(body.image_ids)) if body.image_ids is not None else list(project.entries)
    )
    if not ids or any(image_id not in project.entries for image_id in ids):
        raise ValueError("Choose a non-empty image range belonging to this project")
    counts = {"excluded": 0, "review_state": 0, "no_content": 0, "eligible": 0, "invalid": 0}
    errors = []
    for image_id in ids:
        try:
            with project.lock:
                annotation = project.annotation(image_id, materialize=False)
            if annotation.excluded:
                counts["excluded"] += 1
            elif getattr(annotation, target_task(body) + "_review") not in body.review_states:
                counts["review_state"] += 1
            elif not eligible(annotation, body):
                counts["no_content"] += 1
            else:
                counts["eligible"] += 1
        except Exception as error:
            counts["invalid"] += 1
            if len(errors) < 20:
                errors.append({"image": project.entries[image_id]["path"], "error": str(error)})
    return {
        "input_total": len(ids),
        "counts": counts,
        "total": counts["eligible"] + counts["invalid"],
        "errors": errors,
    }
