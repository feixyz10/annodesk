"""Validated persisted annotation types; geometry is always in original pixels."""

from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def uid() -> str:
    return str(uuid4())


class Point(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    x: float
    y: float
    positive: bool = True


class Instance(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    id: str = Field(default_factory=uid)
    class_id: str | None = None
    box: list[float] | None = None
    polygons: list[list[list[float]]] = Field(default_factory=list)
    mask: dict | None = None
    points: list[Point] = Field(default_factory=list)
    prompt_box: list[float] | None = None
    hidden: bool = False
    locked: bool = False
    source: str = "manual"

    @model_validator(mode="after")
    def geometry(self):
        for box in (self.box, self.prompt_box):
            if box is not None and (len(box) != 4 or box[2] <= box[0] or box[3] <= box[1]):
                raise ValueError("A box must have four coordinates and positive area")
        for polygon in self.polygons:
            if len(polygon) < 3 or any(len(point) != 2 for point in polygon):
                raise ValueError("A polygon needs at least three xy vertices")
        return self


class Annotation(BaseModel):
    revision: int = Field(default=0, ge=0)
    instances: list[Instance] = Field(default_factory=list)
    detection_review: Literal["pending", "ok", "uncertain"] = "pending"
    segmentation_review: Literal["pending", "ok", "uncertain"] = "pending"
    excluded: bool = False
    tags: list[str] = Field(default_factory=list)
    notes: str = ""
    explicit_empty: dict[str, bool] = Field(default_factory=dict)
