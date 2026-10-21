"""Stable perceptual color suggestions for independent class/tag palettes."""

import itertools

import numpy as np

BASE = ["#26835d", "#a16927", "#456cd6", "#9b4b88", "#287e96", "#817722"]


def oklab(colors: list[str]) -> np.ndarray:
    rgb = np.array([[int(c[i : i + 2], 16) / 255 for i in (1, 3, 5)] for c in colors])
    linear = np.where(rgb <= 0.04045, rgb / 12.92, ((rgb + 0.055) / 1.055) ** 2.4)
    lms = (
        linear
        @ np.array(
            [
                [0.4122214708, 0.5363325363, 0.0514459929],
                [0.2119034982, 0.6806995451, 0.1073969566],
                [0.0883024619, 0.2817188376, 0.6299787005],
            ]
        ).T
    )
    return (
        np.cbrt(lms)
        @ np.array(
            [
                [0.2104542553, 0.7936177850, -0.0040720468],
                [1.9779984951, -2.4285922050, 0.4505937099],
                [0.0259040371, 0.7827717662, -0.8086757660],
            ]
        ).T
    )


def choose_color(categories: list[dict]) -> str:
    used = [c["color"] for c in categories]
    for color in BASE:
        if color not in used:
            return color
    candidates = [
        "#" + "".join(f"{v:02x}" for v in rgb)
        for rgb in itertools.product(range(35, 211, 35), repeat=3)
    ]
    lab = oklab(candidates)
    chroma = np.linalg.norm(lab[:, 1:], axis=1)
    valid = (lab[:, 0] > 0.43) & (lab[:, 0] < 0.69) & (chroma > 0.08) & (chroma < 0.23)
    available = [c for c, keep in zip(candidates, valid, strict=True) if keep]
    distances = np.full(len(available), np.inf)
    coordinates = lab[valid]
    for old in oklab(used):
        distances = np.minimum(distances, np.linalg.norm(coordinates - old, axis=1))
    return available[int(distances.argmax())]
