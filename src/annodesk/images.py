"""One decoded first-frame raster for display, inference and exported coordinates."""

import shutil
from pathlib import Path

import numpy as np
from PIL import Image


def load_rgb(path: Path) -> Image.Image:
    # Do not apply ImageOps.exif_transpose here: JPEG annotations already use
    # stored raster coordinates. Pillow itself decodes TIFF orientation, so size
    # and inference must use that same decoded raster rather than a second loader.
    with Image.open(path) as source:
        image = source.convert("RGB")
    image.info.clear()
    return image


def raster_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        if image.format == "TIFF":
            image.load()  # Some Pillow versions finalize TIFF orientation on load.
        return image.size


def inference_image(path: Path) -> np.ndarray:
    # Ultralytics treats ndarray input as BGR and never re-applies file EXIF.
    return np.asarray(load_rgb(path))[:, :, ::-1].copy()


def export_image(source: Path, destination: Path) -> Path:
    with Image.open(source) as image:
        normalize = (
            image.format == "TIFF"
            or image.getexif().get(274, 1) != 1
            or getattr(image, "is_animated", False)
        )
    if normalize:
        destination = destination.with_suffix(".png")
        load_rgb(source).save(destination, format="PNG")
    else:
        shutil.copy2(source, destination)
    return destination
