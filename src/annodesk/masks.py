"""Lossless COCO masks and boundary projection for YOLO/browser display."""

import numpy as np
from pycocotools import mask as coco


def encode_mask(mask: np.ndarray) -> dict:
    encoded = coco.encode(np.asfortranarray(mask.astype(np.uint8)))
    return {"size": list(encoded["size"]), "counts": encoded["counts"].decode("ascii")}


def decode_mask(encoded: dict) -> np.ndarray:
    return coco.decode({"size": encoded["size"], "counts": encoded["counts"].encode("ascii")})


def contours(mask: np.ndarray) -> list[list[list[float]]]:
    """Trace oriented pixel edges; preserve RLE separately because YOLO loses holes."""
    mask = mask.astype(bool)
    padded = np.pad(mask, 1)
    directions = [
        (~padded[:-2, 1:-1] & mask, (0, 0), (1, 0)),
        (~padded[1:-1, 2:] & mask, (1, 0), (1, 1)),
        (~padded[2:, 1:-1] & mask, (1, 1), (0, 1)),
        (~padded[1:-1, :-2] & mask, (0, 1), (0, 0)),
    ]
    edges: dict[tuple[int, int], list[tuple[int, int]]] = {}
    for boundary, start, end in directions:
        ys, xs = np.where(boundary)
        for x, y in zip(xs.tolist(), ys.tolist(), strict=True):
            edges.setdefault((x + start[0], y + start[1]), []).append((x + end[0], y + end[1]))
    polygons = []
    while edges:
        first = next(iter(edges))
        path = [first]
        point = first
        while point in edges:
            targets = edges[point]
            next_point = targets.pop()
            if not targets:
                del edges[point]
            point = next_point
            if point == first:
                break
            path.append(point)
        if len(path) < 3:
            continue
        simplified = []
        for i, point in enumerate(path):
            prev, nxt = path[i - 1], path[(i + 1) % len(path)]
            if (point[0] - prev[0]) * (nxt[1] - point[1]) != (point[1] - prev[1]) * (
                nxt[0] - point[0]
            ):
                simplified.append(list(point))
        area = sum(
            a[0] * b[1] - b[0] * a[1] for a, b in zip(path, path[1:] + path[:1], strict=True)
        )
        if area > 0 and len(simplified) >= 3:
            polygons.append(simplified)
    return polygons
