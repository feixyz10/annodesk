"""Conservative association of separate YOLO box and segmentation instances."""

from annodesk.domain import Instance


def mask_bounds(obj: Instance):
    if obj.mask:
        from pycocotools import mask as coco

        encoded = dict(obj.mask)
        if isinstance(encoded.get("counts"), str):
            encoded["counts"] = encoded["counts"].encode()
        x, y, width, height = coco.toBbox(encoded).tolist()
        return [x, y, x + width, y + height] if width > 0 and height > 0 else None
    points = [point for polygon in obj.polygons for point in polygon]
    if not points:
        return None
    xs, ys = zip(*points, strict=True)
    return [min(xs), min(ys), max(xs), max(ys)]


def overlapping_masks(instances: list[Instance]):
    masks = [
        (index, obj.class_id, bounds)
        for index, obj in enumerate(instances)
        if obj.box is None and (bounds := mask_bounds(obj)) is not None
    ]
    pairs = {}
    for index, obj in enumerate(instances):
        if not obj.box or obj.mask or obj.polygons:
            continue
        x1, y1, x2, y2 = obj.box
        matches = {}
        for other, category, (a1, b1, a2, b2) in masks:
            if obj.class_id is None or category != obj.class_id:
                continue
            intersection = max(0, min(x2, a2) - max(x1, a1)) * max(0, min(y2, b2) - max(y1, b1))
            if intersection > 0:
                union = (x2 - x1) * (y2 - y1) + (a2 - a1) * (b2 - b1) - intersection
                matches[other] = intersection / union
        if matches:
            pairs[index] = matches
    return pairs


def merge_imported_instances(instances: list[Instance]) -> list[Instance]:
    """Only first imports may merge; ambiguous pairs and all geometry are retained."""
    pairs = overlapping_masks(instances)
    uses = {}
    for matches in pairs.values():
        for index in matches:
            uses[index] = uses.get(index, 0) + 1
    merged = set()
    for index, matches in pairs.items():
        if len(matches) != 1:
            continue
        other, iou = next(iter(matches.items()))
        if uses[other] == 1 and iou >= 0.9:
            instances[index].polygons = instances[other].polygons
            instances[index].mask = instances[other].mask
            merged.add(other)
    return [obj for index, obj in enumerate(instances) if index not in merged]


def segmentation_blocked_ids(instances: list[Instance]) -> set[str]:
    """An unresolved same-class mask may already represent this detection box."""
    return {instances[index].id for index in overlapping_masks(instances)}
