"""Check pixels as well as dimensions: orientation mistakes can silently mislabel data."""

import io
import json
from types import SimpleNamespace

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from annodesk.app import create_app
from annodesk.detector import DetectionAdapter
from annodesk.domain import Instance
from annodesk.images import export_image, inference_image, load_rgb
from annodesk.inference import SegmentRequest, UltralyticsAdapter
from annodesk.lifecycle import export_project
from annodesk.masks import decode_mask, encode_mask
from annodesk.storage import Project

TRANSFORMS = {
    2: Image.Transpose.FLIP_LEFT_RIGHT,
    3: Image.Transpose.ROTATE_180,
    4: Image.Transpose.FLIP_TOP_BOTTOM,
    5: Image.Transpose.TRANSPOSE,
    6: Image.Transpose.ROTATE_270,
    7: Image.Transpose.TRANSVERSE,
    8: Image.Transpose.ROTATE_90,
}


def oriented_image(path, kind, orientation):
    pixels = np.zeros((80, 120, 3), dtype=np.uint8)
    pixels[:40, :60] = [240, 20, 30]
    pixels[:40, 60:] = [20, 230, 40]
    pixels[40:, :60] = [30, 40, 220]
    pixels[40:, 60:] = [220, 210, 20]
    original = Image.fromarray(pixels)
    exif = Image.Exif()
    exif[274] = orientation
    original.save(path, format=kind, exif=exif)
    if kind == "TIFF":
        # Pillow's TIFF decoder applies its format orientation while JPEG does not.
        expected = original.transpose(TRANSFORMS[orientation]) if orientation != 1 else original
    else:
        with Image.open(path) as image:
            expected = image.convert("RGB")  # Stored JPEG raster, including compression loss.
    return np.asarray(expected)


@pytest.mark.parametrize("kind,suffix", [("JPEG", ".jpg"), ("TIFF", ".tif")])
@pytest.mark.parametrize("orientation", range(1, 9))
def test_preview_thumbnail_inference_and_export_share_one_raster(
    tmp_path, kind, suffix, orientation
):
    (tmp_path / "images").mkdir()
    source = tmp_path / "images" / ("example" + suffix)
    expected = oriented_image(source, kind, orientation)
    before = source.read_bytes()
    project = Project(tmp_path)
    category = project.add_category("Object")
    image_id = project.images()[0]["id"]
    height, width = expected.shape[:2]
    assert project.image_size(image_id) == (width, height)
    assert np.array_equal(inference_image(source)[:, :, ::-1], expected)
    ann = project.annotation(image_id)
    mask = np.zeros((height, width), dtype=np.uint8)
    mask[10:20, 15:30] = 1
    ann.instances = [
        Instance(class_id=category["id"], box=[15, 10, 30, 20], mask=encode_mask(mask))
    ]
    project.save(image_id, ann)

    with TestClient(create_app(project=tmp_path)) as client:
        metadata = client.get(f"/api/v1/images/{image_id}/annotation").json()
        assert (metadata["width"], metadata["height"]) == (width, height)
        response = client.get(f"/api/v1/images/{image_id}/file")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        with Image.open(io.BytesIO(response.content)) as preview:
            assert preview.size == (width, height)
            assert preview.getexif().get(274) is None
            assert np.array_equal(np.asarray(preview), expected)
        response = client.get(f"/api/v1/images/{image_id}/thumbnail?size=48")
        with Image.open(io.BytesIO(response.content)) as thumbnail:
            target = Image.fromarray(expected)
            target.thumbnail((48, 48))
            assert thumbnail.size == target.size
            # Thumbnail JPEG is lossy; compare interior corner colors with tolerance.
            for xy in ((4, 4), (thumbnail.width - 5, thumbnail.height - 5)):
                assert (
                    np.max(
                        np.abs(np.array(thumbnail.getpixel(xy), dtype=int) - target.getpixel(xy))
                    )
                    < 20
                )

    for task, format in (("detection", "yolo"), ("segmentation", "coco")):
        output = export_project(project, task, format, include_pending=True)
        # TIFF/EXIF files are normalized in the exported copy, never in the project.
        exported = next((output / "images").iterdir())
        with Image.open(exported) as image:
            assert image.size == (width, height)
            assert image.getexif().get(274, 1) == 1
            assert np.array_equal(np.asarray(image), expected)
        if format == "yolo":
            label = (output / "labels/example.txt").read_text().split()
            assert [float(value) for value in label[1:]] == pytest.approx(
                [22.5 / width, 15 / height, 15 / width, 10 / height]
            )
        else:
            record = json.loads((output / "annotations.json").read_text())
            assert record["images"][0]["file_name"] == "images/" + exported.name
            assert record["images"][0]["width"] == width
            assert record["images"][0]["height"] == height
            assert np.array_equal(decode_mask(record["annotations"][0]["segmentation"]), mask)
    assert source.read_bytes() == before


@pytest.mark.parametrize("kind,suffix", [("JPEG", ".jpg"), ("TIFF", ".tiff")])
def test_sam_and_detector_receive_the_same_bgr_raster_as_the_preview(
    tmp_path, monkeypatch, kind, suffix
):
    path = tmp_path / ("input" + suffix)
    rgb = oriented_image(path, kind, 6)
    received = []
    adapter = UltralyticsAdapter(registry=object())
    monkeypatch.setattr(adapter, "_load", lambda *_: None)

    class Predictor:
        def set_image(self, image):
            received.append(image)

        def __call__(self, **kwargs):
            return []

    adapter.predictor = Predictor()
    for candidates in (False, True):
        assert (
            adapter._predict(path, None, "sam2", [15, 10, 30, 20], [], "", candidates=candidates)
            == []
        )
    assert len(received) == 1  # The shared image-embedding cache remains effective.
    detector = DetectionAdapter(registry=object())
    monkeypatch.setattr(detector, "load", lambda _: None)
    detector.model = SimpleNamespace(
        device="cpu", predict=lambda image, **kwargs: received.append(image) or []
    )
    assert detector.detect(path, SegmentRequest()) == []
    assert len(received) == 2
    for bgr in received:
        assert bgr.flags.c_contiguous
        assert np.array_equal(bgr[:, :, ::-1], rgb)


def test_tiff_preview_and_export_use_first_frame(tmp_path):
    path = tmp_path / "frames.tiff"
    Image.new("RGB", (30, 20), "red").save(
        path, save_all=True, append_images=[Image.new("RGB", (30, 20), "blue")]
    )
    assert load_rgb(path).size == (30, 20)
    assert load_rgb(path).getpixel((0, 0)) == (255, 0, 0)
    output = tmp_path / "export"
    output.mkdir()
    exported = export_image(path, output / path.name)
    assert exported.suffix == ".png"
    with Image.open(exported) as image:
        assert image.size == (30, 20)
        assert image.getpixel((0, 0)) == (255, 0, 0)
        assert getattr(image, "n_frames", 1) == 1
    with Image.open(path) as original:
        assert original.n_frames == 2
