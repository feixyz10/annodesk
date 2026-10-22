"""Local-only model registry. Repository IDs are directory names, never downloads."""

import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ModelEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    backend: Literal["sam", "sam2", "mobile_sam", "sam3"]
    source: str = Field(min_length=1)

    @model_validator(mode="after")
    def local_only(self):
        if "://" in self.source:
            raise ValueError("Model URLs are not allowed; use a local path or repository ID")
        return self


class ModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    default_model: str
    models: list[ModelEntry] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_models(self):
        ids = [model.id for model in self.models]
        if len(set(ids)) != len(ids) or self.default_model not in ids:
            raise ValueError("Model IDs must be unique and default_model must exist")
        return self


class ModelRegistry:
    def __init__(self, path: Path | None = None):
        if path is None:
            configured = os.environ.get("ANNODESK_MODELS_CONFIG")
            source_default = Path(__file__).resolve().parents[2] / "models.json"
            path = (
                Path(configured)
                if configured
                else Path.cwd() / "models.json"
                if (Path.cwd() / "models.json").is_file()
                else source_default
                if source_default.is_file()
                else Path(__file__).with_name("models.json")
            )
        self.path = path.expanduser().resolve()
        self.reload()

    def reload(self):
        try:
            self.config = ModelConfig.model_validate_json(self.path.read_text())
        except OSError as error:
            raise ValueError(f"Cannot read model configuration: {self.path}") from error

    def entry(self, model_id: str) -> ModelEntry:
        selected = model_id or self.config.default_model
        for entry in self.config.models:
            if entry.id == selected:
                return entry
        raise ValueError(f"Unknown model ID: {selected}. Select an ID from models.json")

    def resolve(self, model_id: str) -> Path:
        entry = self.entry(model_id)
        source = Path(os.path.expandvars(entry.source)).expanduser()
        candidate = (source if source.is_absolute() else self.path.parent / source).resolve()
        tried = [candidate]
        if not candidate.is_dir() and not source.is_absolute() and os.environ.get("HF_MODELS"):
            candidate = (
                Path(os.path.expandvars(os.environ["HF_MODELS"])).expanduser() / source
            ).resolve()
            tried.append(candidate)
        if not candidate.is_dir():
            raise ValueError(
                f"Model {entry.id} directory is not available locally. Checked: "
                + ", ".join(map(str, tried))
                + ". source must be a directory, not a weight file. No download will be attempted."
            )
        return candidate

    def weights(self, model_id: str) -> Path:
        """Select a checkpoint inside the resolved directory without downloading."""
        directory = self.resolve(model_id)
        entry = self.entry(model_id)
        patterns = {
            "sam": ("sam_b.pt", "sam_l.pt", "sam_h.pt", "sam_vit_*.pt"),
            "sam2": ("sam2*.pt",),
            "mobile_sam": ("mobile_sam.pt",),
            "sam3": ("sam3*.pt",),
        }
        all_files = sorted(p for p in directory.glob("*.pt") if p.is_file())
        matching = sorted(
            {
                p
                for pattern in patterns[entry.backend]
                for p in directory.glob(pattern)
                if p.is_file()
            }
        )
        candidates = matching or all_files
        if len(candidates) != 1:
            reason = (
                "Multiple checkpoint candidates: " + ", ".join(p.name for p in candidates)
                if candidates
                else "No compatible .pt checkpoint found (safetensors-only repositories are not supported by this adapter)"
            )
            raise ValueError(
                f"Model {entry.id}: {reason} in {directory}. Use a directory containing one model. No download will be attempted."
            )
        return candidates[0].resolve()

    def describe(self) -> dict:
        items = []
        for entry in self.config.models:
            try:
                resolved = str(self.resolve(entry.id))
                weights, error = str(self.weights(entry.id)), None
            except ValueError as problem:
                resolved, weights, error = None, None, str(problem)
            items.append(
                {
                    **entry.model_dump(),
                    "available": weights is not None,
                    "weights": weights,
                    "path": resolved,
                    "error": error,
                    "text_prompts": entry.backend == "sam3",
                }
            )
        return {
            "config": str(self.path),
            "default_model": self.config.default_model,
            "models": items,
        }

    def print_json(self):
        print(json.dumps(self.describe(), indent=2))
