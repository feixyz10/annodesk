"""Read-only export planning and verification of previous dataset copies."""

import hashlib
import json
from pathlib import Path

from annodesk.domain import uid
from annodesk.masks import decode_mask, has_task_geometry
from annodesk.storage import Project, atomic_write, validated_box


def digest(path: Path) -> str:
    if not path.is_file():
        return "missing"
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def selection(annotation, task, include_pending, classes):
    review = getattr(annotation, f"{task}_review")
    if annotation.excluded:
        return "excluded", []
    if review == "uncertain":
        return "uncertain", []
    if review != "ok" and not include_pending:
        return "pending", []
    instances = [
        obj
        for obj in annotation.instances
        if (
            bool(obj.box)
            if task == "detection"
            else (decode_mask(obj.mask).any() if obj.mask else bool(obj.polygons))
        )
    ]
    if any(obj.class_id not in classes for obj in instances):
        return "unassigned", []
    if not instances and not annotation.explicit_empty.get(task):
        return "no_annotations", []
    return None, instances


def _history(project):
    try:
        records = json.loads((project.private / "export-history.json").read_text())
        if not isinstance(records, list):
            return []
        return [
            item
            for item in records
            if isinstance(item, dict)
            and isinstance(item.get("signature"), str)
            and isinstance(item.get("path"), str)
        ]
    except (OSError, ValueError):
        return []


def _intact(path: Path, signature: str) -> bool:
    try:
        manifest = json.loads((path / ".annodesk-export.json").read_text())
        files = manifest["files"]
        return (
            manifest["signature"] == signature
            and bool(files)
            and all(
                Path(name).is_relative_to(".")
                and ".." not in Path(name).parts
                and digest(path / name) == checksum
                for name, checksum in files.items()
            )
            and {p.relative_to(path).as_posix() for p in path.rglob("*") if p.is_file()}
            == set(files) | {".annodesk-export.json"}
        )
    except (OSError, ValueError, KeyError, TypeError):
        return False


def preview_export(
    project: Project,
    task="segmentation",
    format="yolo",
    include_pending=False,
    output: str | None = None,
):
    with project.lock:
        project.ensure_writable()
        signature = hashlib.sha256(
            json.dumps(
                {
                    "schema": 1,
                    "task": task,
                    "format": format,
                    "include_pending": include_pending,
                    "classes": project.metadata["classes"],
                },
                sort_keys=True,
            ).encode()
        )
        counts = dict.fromkeys(("pending", "ok", "uncertain", "excluded"), 0)
        skipped = dict.fromkeys(
            ("excluded", "uncertain", "pending", "unassigned", "no_annotations", "invalid"), 0
        )
        errors = []
        no_valid_annotations = dict.fromkeys(counts, 0)
        skipped_by_state = dict.fromkeys((*counts, "unknown"), 0)
        skipped_no_valid_annotations = dict.fromkeys(skipped_by_state, 0)
        skipped_images = []
        eligible = 0
        classes = {c["id"] for c in project.metadata["classes"]}
        for image_id, entry in project.entries.items():
            path = project.image_path(image_id)
            try:
                stamp = path.stat()
                image_stamp = [stamp.st_size, stamp.st_mtime_ns]
            except OSError:
                image_stamp = ["missing"]
            signature.update(
                json.dumps(
                    [
                        entry["path"],
                        image_stamp,
                        digest(project.annotation_path(image_id)),
                        digest(project.label_path(image_id)),
                        digest(project.label_path(image_id, True)),
                    ]
                ).encode()
            )
            state, no_labels = "unknown", False
            try:
                ann = project.annotation(image_id, materialize=False)
                state = "excluded" if ann.excluded else getattr(ann, f"{task}_review")
                counts[state] += 1
                no_labels = not has_task_geometry(ann, task) and not ann.explicit_empty.get(task)
                if no_labels:
                    no_valid_annotations[state] += 1
                if project.annotation_path(image_id).exists():
                    project.validate_fingerprints(image_id)
                reason, instances = selection(ann, task, include_pending, classes)
                if not reason and task == "detection":
                    width, height = project.image_size(image_id)
                    for obj in instances:
                        try:
                            validated_box(obj.box, width, height)
                        except ValueError as error:
                            raise ValueError(
                                f"{project.annotation_path(image_id)}: instance {obj.id}: {error}"
                            ) from error
                if reason:
                    skipped[reason] += 1
                    skipped_by_state[state] += 1
                    if no_labels:
                        skipped_no_valid_annotations[state] += 1
                    if len(skipped_images) < 100:
                        skipped_images.append({"image": entry["path"], "reason": reason})
                else:
                    eligible += 1
            except (ValueError, OSError, KeyError) as error:
                skipped["invalid"] += 1
                skipped_by_state[state] += 1
                if no_labels:
                    skipped_no_valid_annotations[state] += 1
                if len(skipped_images) < 100:
                    skipped_images.append({"image": entry["path"], "reason": "invalid"})
                errors.append({"image": entry["path"], "error": str(error)})
        token = signature.hexdigest()
        destination = Path(output).expanduser() if output else project.private / "exports" / uid()
        if not destination.is_absolute():
            destination = project.root / destination
        destination = destination.resolve()
        previous = next(
            (
                str(p)
                for item in reversed(_history(project))
                if item["signature"] == token
                and (not output or Path(item["path"]) == destination)
                and _intact(p := Path(item["path"]), token)
            ),
            None,
        )
        if not previous:
            if (
                destination == project.root
                or destination in project.root.parents
                or (
                    destination.is_relative_to(project.root)
                    and not destination.is_relative_to(project.private / "exports")
                )
            ):
                raise ValueError("Export to a new directory outside the working dataset")
            if destination.exists():
                raise ValueError("Export directory already exists; choose a new directory")
        return {
            "total": len(project.entries),
            "counts": counts,
            "no_valid_annotations": no_valid_annotations,
            "eligible": eligible,
            "skipped": skipped,
            "skipped_by_state": skipped_by_state,
            "skipped_no_valid_annotations": skipped_no_valid_annotations,
            "errors": errors,
            "skipped_images": skipped_images,
            "signature": token,
            "output": previous or str(destination),
            "already_exported": bool(previous),
        }


def record_export(project, output, signature, check_cancelled=lambda: None):
    files = {}
    for path in output.rglob("*"):
        check_cancelled()
        if path.is_file():
            files[path.relative_to(output).as_posix()] = digest(path)
    check_cancelled()
    atomic_write(
        output / ".annodesk-export.json", json.dumps({"signature": signature, "files": files})
    )
    history = _history(project)
    history.append({"signature": signature, "path": str(output)})
    atomic_write(project.private / "export-history.json", json.dumps(history))
