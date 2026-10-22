"""Project-wide migrations, portable exports and recoverable image removal."""

import hashlib
import json
import shutil
from pathlib import Path
from typing import Literal

import numpy as np
import yaml
from pycocotools import mask as coco

from annodesk.domain import uid
from annodesk.images import export_image
from annodesk.masks import contours, decode_mask
from annodesk.storage import Project, atomic_write, validated_box


def reindex_classes(project: Project, order: list[str] | None = None) -> dict:
    with project.lock:
        project.ensure_writable()
        categories = project.metadata["classes"]
        order = order if order is not None else [c["id"] for c in categories]
        if len(order) != len(categories) or set(order) != {c["id"] for c in categories}:
            raise ValueError("Order must contain every class exactly once")
        mapping = {
            next(c["index"] for c in categories if c["id"] == key): i for i, key in enumerate(order)
        }
        annotations = {image_id: project.annotation(image_id) for image_id in project.entries}
        for image_id in annotations:
            project.validate_fingerprints(image_id)
        outputs = {}
        for image_id, annotation in annotations.items():
            hashes = []
            for seg in (False, True):
                path = project.label_path(image_id, seg)
                text = path.read_text() if path.exists() else ""
                lines = []
                for line in text.splitlines():
                    if line.strip():
                        head, tail = line.split(maxsplit=1)
                        lines.append(f"{mapping[int(head)]} {tail}\n")
                changed = "".join(lines)
                outputs[path] = changed
                hashes.append(hashlib.sha256(changed.encode()).hexdigest())
            record = annotation.model_dump()
            record["revision"] += 1
            record["label_fingerprints"] = hashes
            outputs[project.annotation_path(image_id)] = json.dumps(record)
        updated = json.loads(json.dumps(project.metadata))
        updated["classes"] = [
            next(c for c in updated["classes"] if c["id"] == key) for key in order
        ]
        for i, category in enumerate(updated["classes"]):
            category["index"] = i
        outputs[project.private / "project.json"] = json.dumps(updated)
        config = yaml.safe_load((project.root / "data.yaml").read_text()) or {}
        config["names"] = {c["index"]: c["name"] for c in updated["classes"]}
        outputs[project.root / "data.yaml"] = yaml.safe_dump(
            config, allow_unicode=True, sort_keys=False
        )
        backup = {
            p.relative_to(project.root).as_posix(): p.read_text() if p.exists() else None
            for p in outputs
        }
        atomic_write(project.private / "operations" / f"reindex-{uid()}.json", json.dumps(backup))
        project.transaction(outputs)
        project.metadata = updated
        for cache in project.root.glob("labels*.cache"):
            cache.unlink(missing_ok=True)
        return {"mapping": mapping, "files": len(outputs)}


def trash_excluded(project: Project) -> str:
    with project.lock:
        project.ensure_writable()
        selected = [
            image_id for image_id in project.entries if project.annotation(image_id).excluded
        ]
        operation = uid()
        folder = project.private / "trash" / operation
        moves = []
        for image_id in selected:
            files = [
                project.image_path(image_id),
                project.label_path(image_id),
                project.label_path(image_id, True),
                project.annotation_path(image_id),
            ]
            for source in files:
                if source.exists():
                    relative = source.relative_to(project.root)
                    target = folder / "files" / relative
                    moves.append((source, target))
        manifest = {
            "images": selected,
            "moves": [
                [str(a.relative_to(project.root)), str(b.relative_to(project.root))]
                for a, b in moves
            ],
        }
        atomic_write(folder / "manifest.json", json.dumps(manifest))
        for source, target in moves:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(source, target)
        for image_id in selected:
            project.entries.pop(image_id)
        project.invalidate_statistics()
        return operation


def restore_trash(project: Project, operation: str):
    if not operation or any(char not in "0123456789abcdef-" for char in operation):
        raise ValueError("Invalid trash operation")
    with project.lock:
        project.ensure_writable()
        manifest_path = project.private / "trash" / operation / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        pairs = []
        for original, trashed in manifest["moves"]:
            target, source = (project.root / original).resolve(), (project.root / trashed).resolve()
            if not target.is_relative_to(project.root) or not source.is_relative_to(
                project.private / "trash"
            ):
                raise ValueError("Invalid restore path")
            if source.exists():
                if target.exists():
                    raise ValueError(f"Restore would overwrite {target}")
                pairs.append((source, target))
        # UUIDs remain authoritative while numeric class IDs may have changed.
        known_classes = {category["id"] for category in project.metadata["classes"]}
        sources = {target: source for source, target in pairs}
        for image_id in manifest["images"]:
            target = project.annotation_path(image_id)
            source = sources.get(target, target)
            if source.exists():
                record = json.loads(source.read_text())
                if any(
                    obj.get("class_id") is not None and obj["class_id"] not in known_classes
                    for obj in record["instances"]
                ):
                    raise ValueError("Cannot restore annotations referencing deleted classes")
        for source, target in pairs:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(source, target)
        fresh = Project(project.root)
        project.entries = fresh.entries
        for image_id in manifest["images"]:
            # Save rebuilds both YOLO projections and their fingerprints together.
            project.save(image_id, project.annotation(image_id))
        manifest["restored"] = True
        atomic_write(manifest_path, json.dumps(manifest))
        project.invalidate_statistics()


def export_project(
    project: Project,
    task: Literal["detection", "segmentation"] = "segmentation",
    format: Literal["yolo", "coco"] = "yolo",
    include_pending: bool = False,
    progress=lambda *_: None,
    cancelled=lambda: False,
) -> Path:
    with project.lock:
        project.ensure_writable()
        output = project.private / "exports" / uid()
        output.mkdir(parents=True)
        categories = sorted(project.metadata["classes"], key=lambda c: c["index"])
        indices = {c["id"]: i for i, c in enumerate(categories)}
        report = {"exported": 0, "skipped": [], "warnings": []}
        config = {"path": ".", "names": {i: c["name"] for i, c in enumerate(categories)}}
        coco_data = {
            "images": [],
            "annotations": [],
            "categories": [{"id": i, "name": c["name"]} for i, c in enumerate(categories)],
        }
        split_paths = {}

        def check_cancelled():
            if cancelled():
                shutil.rmtree(output)
                raise ValueError("Export cancelled; incomplete output removed")

        for completed, image_id in enumerate(project.entries, 1):
            check_cancelled()
            progress(completed - 1, len(project.entries))
            check_cancelled()
            ann = project.annotation(image_id)
            review = getattr(ann, f"{task}_review")
            if ann.excluded or review == "uncertain" or (review != "ok" and not include_pending):
                report["skipped"].append(project.entries[image_id]["path"])
                continue
            if task == "detection":
                instances = [o for o in ann.instances if o.box]
            else:
                instances = [
                    o
                    for o in ann.instances
                    if (decode_mask(o.mask).any() if o.mask else bool(o.polygons))
                ]
            if (not instances and not ann.explicit_empty.get(task)) or any(
                o.class_id not in indices for o in instances
            ):
                report["skipped"].append(project.entries[image_id]["path"])
                continue
            relative = Path(project.entries[image_id]["path"])
            destination = output / "images" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination = export_image(project.image_path(image_id), destination)
            relative = destination.relative_to(output / "images")
            width, height = project.image_size(image_id)
            split = (
                relative.parts[0]
                if len(relative.parts) > 1 and relative.parts[0] in {"train", "val", "test"}
                else "unassigned"
            )
            split_paths.setdefault(split, []).append("./images/" + relative.as_posix())
            lines = []
            image_index = len(coco_data["images"]) + 1
            coco_data["images"].append(
                {
                    "id": image_index,
                    "file_name": "images/" + relative.as_posix(),
                    "width": width,
                    "height": height,
                }
            )
            for obj in instances:
                index = indices[obj.class_id]
                if task == "detection":
                    try:
                        x1, y1, x2, y2 = validated_box(obj.box, width, height)
                    except ValueError as error:
                        raise ValueError(
                            f"{project.annotation_path(image_id)}: instance {obj.id}: {error}"
                        ) from error
                    values = [
                        (x1 + x2) / 2 / width,
                        (y1 + y2) / 2 / height,
                        (x2 - x1) / width,
                        (y2 - y1) / height,
                    ]
                    lines.append(f"{index} " + " ".join(f"{v:.8g}" for v in values))
                    segmentation = []
                    bbox, area = [x1, y1, x2 - x1, y2 - y1], (x2 - x1) * (y2 - y1)
                else:
                    polygons = contours(decode_mask(obj.mask)) if obj.mask else obj.polygons
                    for polygon in polygons:
                        values = [v for x, y in polygon for v in (x / width, y / height)]
                        lines.append(f"{index} " + " ".join(f"{v:.8g}" for v in values))
                    if obj.mask:
                        segmentation = obj.mask
                        encoded = {
                            "size": segmentation["size"],
                            "counts": segmentation["counts"].encode(),
                        }
                    else:
                        encoded = coco.merge(
                            coco.frPyObjects(
                                [np.array(p).flatten().tolist() for p in obj.polygons],
                                height,
                                width,
                            )
                        )
                        segmentation = {
                            "size": list(encoded["size"]),
                            "counts": encoded["counts"].decode(),
                        }
                    bbox, area = coco.toBbox(encoded).tolist(), float(coco.area(encoded))
                    if obj.mask or len(obj.polygons) > 1:
                        report["warnings"].append(
                            f"{relative}: YOLO polygon projection may lose holes or split an instance; COCO RLE preserves masks"
                        )
                coco_data["annotations"].append(
                    {
                        "id": len(coco_data["annotations"]) + 1,
                        "image_id": image_index,
                        "category_id": index,
                        "bbox": bbox,
                        "area": area,
                        "segmentation": segmentation,
                        "iscrowd": 0,
                    }
                )
            label = output / "labels" / relative.with_suffix(".txt")
            atomic_write(label, "\n".join(lines) + ("\n" if lines else ""))
            report["exported"] += 1
        progress(len(project.entries), len(project.entries), "packaging")
        check_cancelled()
        for split, paths in split_paths.items():
            check_cancelled()
            atomic_write(output / f"{split}.txt", "\n".join(paths) + "\n")
            if split != "unassigned":
                config[split] = f"{split}.txt"
        if not config.get("train") or not config.get("val"):
            report["warnings"].append(
                "Training requires train/val splits; unassigned.txt is a review list, not a completed training config"
            )
        atomic_write(
            output / "data.yaml", yaml.safe_dump(config, allow_unicode=True, sort_keys=False)
        )
        check_cancelled()
        atomic_write(
            output / "class-id-map.json",
            json.dumps({c["index"]: indices[c["id"]] for c in categories}, indent=2),
        )
        check_cancelled()
        atomic_write(output / "report.json", json.dumps(report, indent=2))
        check_cancelled()
        if format == "coco":
            atomic_write(output / "annotations.json", json.dumps(coco_data))
        check_cancelled()
        return output
