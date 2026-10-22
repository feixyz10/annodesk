"""Synchronous box-to-mask conversion without an HTTP server or browser."""

import json
from pathlib import Path

from annodesk.inference import SegmentationService, SegmentRequest, UltralyticsAdapter
from annodesk.models import ModelRegistry
from annodesk.storage import Project, atomic_write


def segment_dataset(project: Path, model: str, registry: ModelRegistry) -> dict:
    # Fail before touching dataset metadata if the selected checkpoint is missing.
    registry.weights(model)
    dataset = Project(project)
    service = SegmentationService(dataset, adapter=UltralyticsAdapter(registry))
    report = {"model": registry.entry(model).id, "processed": 0, "skipped": 0, "failed": []}
    report_path = dataset.private / "segment-report.json"
    try:
        for image_id in dataset.entries:
            try:
                annotation = dataset.annotation(image_id)
                if annotation.excluded or not any(
                    o.box and not o.mask and not o.polygons and not o.locked
                    for o in annotation.instances
                ):
                    report["skipped"] += 1
                else:
                    service.process(image_id, SegmentRequest(model=model))
                    report["processed"] += 1
            except Exception as error:
                report["failed"].append(
                    {"image": dataset.entries[image_id]["path"], "error": str(error)}
                )
            atomic_write(report_path, json.dumps(report, indent=2))
            print(json.dumps({"image": dataset.entries[image_id]["path"], **report}), flush=True)
    finally:
        service.close()
        atomic_write(report_path, json.dumps(report, indent=2))
    return report
