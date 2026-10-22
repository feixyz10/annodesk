"""HTTP contracts shared by bundled and separately hosted clients."""

import hashlib
import io
import json
from pathlib import Path
from typing import Literal

import numpy as np
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response
from PIL import Image
from pydantic import BaseModel, Field

from annodesk.domain import Annotation
from annodesk.events import EventLog
from annodesk.inference import SegmentationService, SegmentRequest, UltralyticsAdapter
from annodesk.jobs import BatchJobs
from annodesk.lease import ProjectLease
from annodesk.lifecycle import export_project, reindex_classes, restore_trash, trash_excluded
from annodesk.masks import decode_mask
from annodesk.models import ModelRegistry
from annodesk.statistics import StatisticsIndex
from annodesk.storage import Project


class OpenProject(BaseModel):
    path: str


class ExportInput(BaseModel):
    task: Literal["detection", "segmentation"] = "segmentation"
    format: Literal["yolo", "coco"] = "yolo"
    include_pending: bool = False


class ReindexInput(BaseModel):
    order: list[str] | None = None


class CategoryInput(BaseModel):
    name: str
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


def project_routes(
    initial: Path | None = None, models_config: Path | None = None, events: EventLog | None = None
) -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    events = events or EventLog()
    lease = ProjectLease(initial) if initial else None
    try:
        current = Project(initial) if initial else None
    except BaseException:
        if lease:
            lease.close()
        raise
    registry = ModelRegistry(models_config)

    services = {}
    batches = {}

    def service():
        item = project()
        existing = services.get(item.metadata["id"])
        if existing is None or existing.project is not item:
            if existing is not None:
                existing.close()
            batches.pop(item.metadata["id"], None)
            services[item.metadata["id"]] = SegmentationService(
                item, adapter=UltralyticsAdapter(registry, events=events)
            )
        return services[item.metadata["id"]]

    def batch():
        item = service()
        if item.project.metadata["id"] not in batches:
            batches[item.project.metadata["id"]] = BatchJobs(item, events)
        return batches[item.project.metadata["id"]]

    def project() -> Project:
        if current is None:
            raise HTTPException(409, "Open a project first")
        return current

    @router.post("/project/open")
    def open_project(body: OpenProject):
        nonlocal current, lease
        if any(s.active for s in services.values()) or any(
            any(j["status"] == "running" for j in b.records.values()) for b in batches.values()
        ):
            raise ValueError(
                "Wait for inference or cancel the running batch before changing projects"
            )
        if current and current.root == Path(body.path).expanduser().resolve():
            return get_project()
        replacement_lease = ProjectLease(Path(body.path))
        try:
            replacement = Project(Path(body.path))
        except BaseException:
            replacement_lease.close()
            raise
        for old in services.values():
            old.close()
        services.clear()
        batches.clear()
        if lease:
            lease.close()
        lease = replacement_lease
        current = replacement
        events.emit(
            "INFO",
            f"Project opened: {current.root}",
            event_type="project_open",
            project_id=current.metadata["id"],
        )
        return {**current.metadata, "root": str(current.root), "image_count": len(current.entries)}

    @router.get("/models")
    def list_models():
        registry.reload()
        return registry.describe()

    @router.get("/project")
    def get_project():
        if current is None:
            return None
        item = project()
        return {**item.metadata, "root": str(item.root), "image_count": len(item.entries)}

    @router.get("/project/statistics")
    def statistics(task: Literal["detection", "segmentation"] = "segmentation"):
        item = project()
        with item.lock:
            if item.statistics is None:
                item.statistics = StatisticsIndex(item)
        return item.statistics.read(task)

    @router.get("/images")
    def images(offset: int = Query(0, ge=0), limit: int = Query(200, ge=1, le=1000)):
        items = project().images()
        return {"items": items[offset : offset + limit], "total": len(items)}

    @router.get("/images/{image_id}/file")
    def image_file(image_id: str):
        return FileResponse(project().image_path(image_id))

    @router.get("/images/{image_id}/thumbnail")
    def thumbnail(image_id: str, size: int = Query(240, ge=48, le=320)):
        item = project()
        path = item.image_path(image_id)
        stat = path.stat()
        key = hashlib.sha256(
            f"{path}:{stat.st_mtime_ns}:{stat.st_size}:{size}:v1".encode()
        ).hexdigest()
        cache = item.private / "thumbnails"
        cache.mkdir(exist_ok=True)
        target = cache / f"{key}.jpg"
        with item.lock:
            if not target.exists():
                with Image.open(path) as image:
                    image.thumbnail((size, size))
                    output = io.BytesIO()
                    image.convert("RGB").save(output, format="JPEG", quality=80)
                target.write_bytes(output.getvalue())
                files = sorted(cache.glob("*.jpg"), key=lambda file: file.stat().st_mtime)
                budget = sum(file.stat().st_size for file in files)
                for old in files:
                    if budget <= 512 * 1024 * 1024:
                        break
                    if old != target:
                        budget -= old.stat().st_size
                        old.unlink(missing_ok=True)
            else:
                target.touch()
            return Response(
                target.read_bytes(),
                media_type="image/jpeg",
                headers={"Cache-Control": "private, max-age=300"},
            )

    @router.get("/images/{image_id}/annotation")
    def annotation(image_id: str):
        item = project()
        with item.lock:
            ann = item.annotation(image_id)
            width, height = item.image_size(image_id)
            return {**ann.model_dump(), "width": width, "height": height}

    @router.put("/images/{image_id}/annotation")
    def save(image_id: str, body: Annotation):
        return project().save(image_id, body)

    @router.post("/classes")
    def add_class(body: CategoryInput):
        return project().add_category(body.name, body.color)

    @router.post("/tags")
    def add_tag(body: CategoryInput):
        return project().add_category(body.name, body.color, tag=True)

    @router.patch("/categories/{category_id}")
    def update_category(category_id: str, body: CategoryInput):
        item = project()
        with item.lock:
            entries = item.metadata["classes"] + item.metadata["tags"]
            category = next((c for c in entries if c["id"] == category_id), None)
            if category is None:
                raise KeyError("Unknown category")
            category["name"] = body.name.strip()
            if not category["name"]:
                raise ValueError("Name must not be empty")
            if body.color:
                category["color"] = body.color
            item.write_metadata()
            return category

    @router.post("/classes/reindex")
    def reindex(body: ReindexInput):
        return reindex_classes(project(), body.order)

    @router.post("/export")
    def export(body: ExportInput):
        output = export_project(project(), body.task, body.format, body.include_pending)
        return {
            "path": str(output),
            "report": json.loads((output / "report.json").read_text()),
        }

    @router.post("/export/jobs")
    def export_job(body: ExportInput):
        return batch().export(body.task, body.format, body.include_pending)

    @router.post("/trash/excluded")
    def trash():
        return {"operation": trash_excluded(project())}

    @router.post("/trash/{operation}/restore")
    def restore(operation: str):
        restore_trash(project(), operation)
        return {"restored": True}

    @router.post("/images/{image_id}/segment")
    def segment(image_id: str, body: SegmentRequest):
        item = service()
        return item.executor.submit(item.process, image_id, body).result()

    @router.get("/jobs")
    def list_jobs():
        return list(batch().records.values())

    @router.post("/jobs")
    def create_job(body: SegmentRequest):
        return batch().start(body)

    @router.post("/jobs/{job_id}/resume")
    def resume_job(job_id: str):
        item = batch()
        return item.start(SegmentRequest.model_validate(item.records[job_id]["request"]), job_id)

    @router.get("/jobs/{job_id}")
    def get_job(job_id: str):
        return batch().records[job_id]

    @router.delete("/jobs/{job_id}")
    def cancel_job(job_id: str):
        return batch().cancel(job_id)

    @router.get("/images/{image_id}/masks/{instance_id}")
    def mask_image(image_id: str, instance_id: str):
        item = project()
        annotation = item.annotation(image_id)
        obj = next((o for o in annotation.instances if o.id == instance_id), None)
        if obj is None or not obj.mask:
            raise KeyError("No mask")
        binary = decode_mask(obj.mask)
        color = next(
            (c["color"] for c in item.metadata["classes"] if c["id"] == obj.class_id), "#657286"
        )
        rgba = np.zeros((*binary.shape, 4), dtype=np.uint8)
        rgba[:, :, :3] = [int(color[i : i + 2], 16) for i in (1, 3, 5)]
        rgba[:, :, 3] = binary * 110
        output = io.BytesIO()
        Image.fromarray(rgba).save(output, format="PNG")
        return Response(
            output.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"}
        )

    # Keep access local to this application instance rather than a module global.
    def close():
        for item in batches.values():
            item.close()
        for item in services.values():
            item.close()
        if lease:
            lease.close()

    router.close = close
    router.project = project
    return router
