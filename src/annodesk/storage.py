"""YOLO project storage with journaled multi-file saves and revision checks."""

import hashlib
import json
import math
import os
import threading
from pathlib import Path

import yaml

from annodesk.colors import choose_color
from annodesk.domain import Annotation, Instance, uid
from annodesk.images import raster_size
from annodesk.masks import contours, decode_mask

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}


class RevisionConflict(ValueError):
    pass


def atomic_write(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uid()}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def fingerprint(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "missing"


class Project:
    def __init__(self, directory: Path):
        directory = directory.expanduser().resolve()
        if not directory.is_dir():
            raise ValueError("Project directory does not exist")
        self.root = directory
        self.images_root = directory / "images" if (directory / "images").is_dir() else directory
        self.private = directory / ".annodesk"
        self.lock = threading.RLock()
        self.private.mkdir(exist_ok=True)
        self._recover()
        meta_path = self.private / "project.json"
        self.metadata = (
            json.loads(meta_path.read_text())
            if meta_path.exists()
            else {"id": uid(), "classes": [], "tags": [], "format": 1}
        )
        self.entries = {}
        stems = set()
        for path in sorted(self.images_root.rglob("*")):
            if path.suffix.lower() not in IMAGE_SUFFIXES or not path.is_file():
                continue
            rel = path.relative_to(self.images_root)
            if any(part.startswith(".") for part in rel.parts):
                continue
            stem = rel.with_suffix("").as_posix()
            if stem in stems:
                raise ValueError(f"Images with the same label path: {stem}")
            stems.add(stem)
            image_id = hashlib.sha256(rel.as_posix().encode()).hexdigest()[:24]
            self.entries[image_id] = {"id": image_id, "path": rel.as_posix()}
        if not self.metadata["classes"]:
            self._import_classes()
        self.write_metadata()
        self.statistics = None

    def invalidate_statistics(self):
        if self.statistics is not None:
            self.statistics.refresh()

    def _recover(self):
        operation = self.private / "pending.json"
        if operation.exists():
            for relative, value in json.loads(operation.read_text()).items():
                path = (self.root / relative).resolve()
                if not path.is_relative_to(self.root):
                    raise ValueError("Invalid recovery path")
                atomic_write(path, value)
            operation.unlink()

    def transaction(self, outputs: dict[Path, str]):
        with self.lock:
            self.ensure_writable()
            values = {
                path.relative_to(self.root).as_posix(): text for path, text in outputs.items()
            }
            atomic_write(self.private / "pending.json", json.dumps(values))
            self._recover()

    def ensure_writable(self):
        if (self.private / "pending.json").exists():
            raise RevisionConflict(
                "An unfinished project transaction requires recovery; restart the backend before writing."
            )

    def _import_classes(self):
        config = self.root / "data.yaml"
        data = yaml.safe_load(config.read_text()) if config.exists() else {}
        if data is not None and not isinstance(data, dict):
            raise ValueError("data.yaml must contain a mapping")
        names = (data or {}).get("names", {})
        if isinstance(names, list):
            names = dict(enumerate(names))
        if not isinstance(names, dict):
            raise ValueError("data.yaml names must be a list or dictionary")
        names = {int(key): str(value) for key, value in names.items()}
        ids = set(names)
        for folder in ["labels", "labels_seg"]:
            for label in (self.root / folder).rglob("*.txt"):
                for line in label.read_text().splitlines():
                    if line.strip():
                        try:
                            ids.add(int(line.split()[0]))
                        except ValueError as error:
                            raise ValueError(f"Invalid class ID in {label}") from error
        if ids and (min(ids) < 0 or max(ids) > 10000):
            raise ValueError("Class IDs must be between 0 and 10000")
        for i in sorted(ids):
            self.metadata["classes"].append(
                {
                    "id": uid(),
                    "index": i,
                    "name": names.get(i, f"class_{i}"),
                    "color": default_color(i),
                }
            )

    def metadata_outputs(self, metadata):
        config = self.root / "data.yaml"
        data = yaml.safe_load(config.read_text()) if config.exists() else {}
        if data is not None and not isinstance(data, dict):
            raise ValueError("data.yaml must contain a mapping")
        data = data or {}
        data["names"] = {
            c["index"]: c["name"] for c in sorted(metadata["classes"], key=lambda c: c["index"])
        }
        return {
            self.private / "project.json": json.dumps(metadata, indent=2),
            config: yaml.safe_dump(data, allow_unicode=True, sort_keys=False),
        }

    def write_metadata(self):
        self.transaction(self.metadata_outputs(self.metadata))

    def image_path(self, image_id: str) -> Path:
        if image_id not in self.entries:
            raise KeyError("Unknown image")
        path = (self.images_root / self.entries[image_id]["path"]).resolve()
        if not path.is_relative_to(self.images_root):
            raise ValueError("Image is outside the project")
        return path

    def label_path(self, image_id: str, segmentation: bool = False) -> Path:
        return (
            self.root
            / ("labels_seg" if segmentation else "labels")
            / Path(self.entries[image_id]["path"]).with_suffix(".txt")
        )

    def annotation_path(self, image_id: str) -> Path:
        return self.private / "annotations" / f"{image_id}.json"

    def images(self) -> list[dict]:
        return list(self.entries.values())

    def annotation(self, image_id: str, *, materialize=True) -> Annotation:
        with self.lock:
            path = self.annotation_path(image_id)
            if path.exists():
                return Annotation.model_validate_json(path.read_text())
            width, height = self.image_size(image_id)
            ann = Annotation()
            classes = {c["index"]: c["id"] for c in self.metadata["classes"]}
            for segmentation in (False, True):
                label = self.label_path(image_id, segmentation)
                if not label.exists():
                    continue
                for number, line in enumerate(label.read_text().splitlines(), 1):
                    if not line.strip():
                        continue
                    try:
                        parts = line.split()
                        category = classes[int(parts[0])]
                        coords = [float(v) for v in parts[1:]]
                        if any(not math.isfinite(v) or not 0 <= v <= 1 for v in coords):
                            raise ValueError("Coordinates must be finite and normalized")
                        if segmentation:
                            if len(coords) < 6 or len(coords) % 2:
                                raise ValueError("Polygon must have at least three points")
                            points = [
                                [coords[i] * width, coords[i + 1] * height]
                                for i in range(0, len(coords), 2)
                            ]
                            ann.instances.append(
                                Instance(class_id=category, polygons=[points], source="yolo")
                            )
                        else:
                            if len(coords) != 4:
                                raise ValueError("Detection annotation must have four coordinates")
                            x, y, w, h = coords
                            ann.instances.append(
                                Instance(
                                    class_id=category,
                                    box=validated_box(
                                        [
                                            (x - w / 2) * width,
                                            (y - h / 2) * height,
                                            (x + w / 2) * width,
                                            (y + h / 2) * height,
                                        ],
                                        width,
                                        height,
                                    ),
                                    source="yolo",
                                )
                            )
                    except (ValueError, KeyError) as error:
                        raise ValueError(f"{label}:{number}: {error}") from error
            # Materialize a stable initial revision without rewriting imported YOLO files.
            if materialize:
                return self._write_initial(image_id, ann)
            return ann

    def _write_initial(self, image_id: str, annotation: Annotation) -> Annotation:
        with self.lock:
            path = self.annotation_path(image_id)
            # A delayed initializer must never replace a record another writer committed.
            if path.exists():
                return Annotation.model_validate_json(path.read_text())
            self.ensure_writable()
            record = annotation.model_dump()
            record["label_fingerprints"] = [
                fingerprint(self.label_path(image_id, seg)) for seg in (False, True)
            ]
            atomic_write(path, json.dumps(record))
            return annotation

    def save(self, image_id: str, annotation: Annotation, *, new_classes=None) -> Annotation:
        with self.lock:
            self.ensure_writable()
            old = self.annotation(image_id)
            if annotation.revision != old.revision:
                raise RevisionConflict("Annotation changed. Reload before saving.")
            self.validate_fingerprints(image_id)
            width, height = self.image_size(image_id)
            metadata = json.loads(json.dumps(self.metadata))
            for category in new_classes or []:
                if any(
                    c["id"] == category["id"]
                    or c["index"] == category["index"]
                    or c["name"] == category["name"]
                    for c in metadata["classes"]
                ):
                    raise ValueError("New class conflicts with an existing class")
                metadata["classes"].append(category)
            metadata["classes"].sort(key=lambda c: c["index"])
            indices = {c["id"]: c["index"] for c in metadata["classes"]}
            detection, segmentation = [], []
            ids = [instance.id for instance in annotation.instances]
            if len(ids) != len(set(ids)):
                raise ValueError("Duplicate instance IDs")
            for instance in annotation.instances:
                if instance.class_id is not None and instance.class_id not in indices:
                    raise ValueError("Unknown class")
                index = indices.get(instance.class_id)
                if instance.prompt_box:
                    x1, y1, x2, y2 = instance.prompt_box
                    if x1 < 0 or y1 < 0 or x2 > width or y2 > height:
                        raise ValueError("Prompt box outside image")
                if instance.mask is not None:
                    if instance.mask.get("size") != [height, width] or not isinstance(
                        instance.mask.get("counts"), str
                    ):
                        raise ValueError("Invalid mask dimensions or counts")
                    try:
                        decoded = decode_mask(instance.mask)
                    except Exception as error:
                        raise ValueError("Invalid mask encoding") from error
                    if decoded.shape != (height, width):
                        raise ValueError("Invalid mask dimensions")
                    instance.polygons = contours(decoded)
                if instance.box:
                    instance.box = validated_box(instance.box, width, height)
                    x1, y1, x2, y2 = instance.box
                    if index is not None:
                        detection.append(
                            format_line(
                                index,
                                [
                                    (x1 + x2) / 2 / width,
                                    (y1 + y2) / 2 / height,
                                    (x2 - x1) / width,
                                    (y2 - y1) / height,
                                ],
                            )
                        )
                for polygon in instance.polygons:
                    if any(x < 0 or y < 0 or x > width or y > height for x, y in polygon):
                        raise ValueError("Polygon outside image")
                    if index is not None:
                        segmentation.append(
                            format_line(
                                index,
                                [value for x, y in polygon for value in (x / width, y / height)],
                            )
                        )
            updated = annotation.model_copy(deep=True)
            updated.revision += 1
            labels = ["".join(detection), "".join(segmentation)]
            record = updated.model_dump()
            record["label_fingerprints"] = [
                hashlib.sha256(text.encode()).hexdigest() for text in labels
            ]
            self.transaction(
                {
                    **(self.metadata_outputs(metadata) if new_classes else {}),
                    self.annotation_path(image_id): json.dumps(record),
                    **{self.label_path(image_id, seg): labels[int(seg)] for seg in (False, True)},
                }
            )
            if new_classes:
                self.metadata = metadata
            if self.statistics is not None:
                self.statistics.update(image_id, updated)
            return updated

    def validate_fingerprints(self, image_id: str):
        self.annotation(image_id)
        record = json.loads(self.annotation_path(image_id).read_text())
        expected = record.get("label_fingerprints")
        actual = [fingerprint(self.label_path(image_id, seg)) for seg in (False, True)]
        if expected is not None and expected != actual:
            raise RevisionConflict(
                "YOLO labels changed outside AnnoDesk; reopen or reconcile them."
            )

    def image_size(self, image_id: str) -> tuple[int, int]:
        return raster_size(self.image_path(image_id))

    def add_category(self, name: str, color: str | None = None, tag: bool = False) -> dict:
        with self.lock:
            name = name.strip()
            if not name:
                raise ValueError("Name must not be empty")
            categories = self.metadata["tags" if tag else "classes"]
            if any(c["name"] == name for c in categories):
                raise ValueError("Name already exists")
            item = {"id": uid(), "name": name, "color": color or choose_color(categories)}
            if not tag:
                item["index"] = max((c["index"] for c in categories), default=-1) + 1
            categories.append(item)
            try:
                self.write_metadata()
            except Exception:
                categories.remove(item)
                raise
            return item


def format_line(index: int, values: list[float]) -> str:
    return f"{index} " + " ".join(f"{value:.8g}" for value in values) + "\n"


def default_color(index: int) -> str:
    return ["#26835d", "#a16927", "#456cd6", "#9b4b88", "#287e96", "#817722"][index % 6]


def validated_box(box: list[float], width: int, height: int) -> list[float]:
    """Reject actual overflow; tolerate only existing YOLO rounding at image edges."""
    if len(box) != 4 or not all(math.isfinite(value) for value in box):
        raise ValueError("Invalid box coordinates")
    x1, y1, x2, y2 = box
    tolerance = max(width, height) * 1e-6
    if x1 < -tolerance or y1 < -tolerance or x2 > width + tolerance or y2 > height + tolerance:
        raise ValueError("Box outside image")
    clipped = [max(0, x1), max(0, y1), min(width, x2), min(height, y2)]
    if clipped[2] <= clipped[0] or clipped[3] <= clipped[1]:
        raise ValueError("Box outside image")
    return clipped
