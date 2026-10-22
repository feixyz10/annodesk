"""Synthetic inference used only in tests, including real spawned child processes."""

import os

import numpy as np
from PIL import Image

from annodesk.execution import ImageExecutor


class Adapter:
    def __init__(self, registry, device):
        self.registry, self.device = registry, device

    def load(self, model):
        if model == "startup-fail":
            raise ValueError("Model load failed")

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
