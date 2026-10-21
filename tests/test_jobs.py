import time

import numpy as np
from PIL import Image

from annodesk.domain import Instance
from annodesk.inference import SegmentationService, SegmentRequest
from annodesk.jobs import BatchJobs
from annodesk.storage import Project


class Adapter:
    def predict(self, *_):
        return [np.ones((20, 30), dtype=np.uint8)]


def test_batch_progress_survives_manager_restart(tmp_path):
    (tmp_path / "images").mkdir()
    Image.new("RGB", (30, 20)).save(tmp_path / "images/a.png")
    project = Project(tmp_path)
    category = project.add_category("Object")
    image_id = project.images()[0]["id"]
    ann = project.annotation(image_id)
    ann.instances = [Instance(class_id=category["id"], box=[1, 1, 29, 19])]
    project.save(image_id, ann)
    service = SegmentationService(project, adapter=Adapter())
    manager = BatchJobs(service)
    job = manager.start(SegmentRequest())
    for _ in range(100):
        if job["status"] == "complete":
            break
        time.sleep(0.01)
    assert job["status"] == "complete"
    assert not job["failed"]
    restored = BatchJobs(service)
    assert restored.records[job["id"]]["completed"] == 1
    assert project.annotation(image_id).instances[0].mask
    service.close()
