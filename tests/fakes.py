"""Synthetic inference used only in tests, including real spawned child processes."""

import os

import numpy as np
from PIL import Image

from annodesk.execution import ImageExecutor


class Adapter:
    def __init__(self, registry, device):
        self.registry, self.device = registry, device

    def load(self, model):
        if self.registry.entry(model).task == "detection":
            from annodesk.classes import read_classes

            return read_classes(self.registry.classes_path(model))
        if model == "startup-fail":
            raise ValueError("Model load failed")

    def detect(self, path, body):
        return [{"box": [1, 2, 9, 10], "class_index": 2, "confidence": 0.9}]

    def predict(self, path, model, *_):
        if model == "fail":
            raise ValueError("Missing local tokenizer")
        if path.stem == "crash":
            os._exit(9)
        with Image.open(path) as image:
            width, height = image.size
        return [np.ones((height, width), dtype=np.uint8)]


def executor(registry, model, plan, events):
    return ImageExecutor(registry, model, plan, events, adapter_factory=Adapter)
