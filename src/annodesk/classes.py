"""Strict class definitions. Numeric IDs and names are never remapped implicitly."""

import json
from pathlib import Path

import yaml


def class_names(value, *, contiguous=True) -> dict[int, str]:
    if isinstance(value, list):
        value = dict(enumerate(value))
    if not isinstance(value, dict) or not value:
        raise ValueError("Class definitions must contain a non-empty names list or dictionary")
    names = {}
    for key, name in value.items():
        try:
            index = int(key)
        except (ValueError, TypeError, OverflowError) as error:
            raise ValueError("Class IDs must be nonnegative integers") from error
        if isinstance(key, bool) or str(key) != str(index) or index < 0:
            raise ValueError("Class IDs must be nonnegative integers")
        if not isinstance(name, str) or not name or name != name.strip():
            raise ValueError("Class names must be non-empty strings without surrounding whitespace")
        names[index] = name
    if len(set(names.values())) != len(names):
        raise ValueError("Class names must be unique")
    if contiguous and set(names) != set(range(len(names))):
        raise ValueError("Model class IDs must be contiguous from 0")
    return dict(sorted(names.items()))


def read_classes(path: Path) -> dict[int, str]:
    try:
        value = (
            json.loads(path.read_text())
            if path.suffix.lower() == ".json"
            else yaml.safe_load(path.read_text())
        )
        if not isinstance(value, dict) or "names" not in value:
            raise ValueError("Class definition file must contain names")
        return class_names(value["names"])
    except OSError as error:
        raise ValueError(f"Cannot read class definition file: {path}") from error


def compatible(names: dict[int, str], metadata: dict) -> dict:
    model = set(names.items())
    project = {(c["index"], c["name"]) for c in metadata["classes"]}
    if not (model <= project or project <= model):
        differences = []
        current = dict(project)
        for index in sorted(names.keys() & current.keys()):
            if names[index] != current[index]:
                differences.append(
                    f"ID {index}: model={names[index]!r}, project={current[index]!r}"
                )
        raise ValueError(
            "Incompatible classes: "
            + (
                "; ".join(differences)
                or "ID/name definitions must be identical or one an exact subset of the other"
            )
        )
    extras = [{"index": index, "name": name} for index, name in sorted(model - project)]
    deleted = {c["index"] for c in metadata.get("deleted_classes", [])}
    if any(c["index"] in deleted for c in extras):
        raise ValueError("Model references a deleted project class; restore it explicitly first")
    return {
        "relation": "equal"
        if model == project
        else "model_subset"
        if model <= project
        else "project_subset",
        "extra_classes": extras,
        "accepted_classes": len(model & project),
    }
