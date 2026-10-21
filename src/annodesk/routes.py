"""HTTP contracts shared by bundled and separately hosted clients."""

import hashlib
import io
import threading
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response
from PIL import Image
from pydantic import BaseModel, Field

from annodesk.domain import Annotation, uid
from annodesk.inference import SegmentationService, SegmentRequest
from annodesk.storage import Project


class OpenProject(BaseModel):
    path: str


class CategoryInput(BaseModel):
    name: str
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


def project_routes(initial: Path | None = None) -> APIRouter:
    router = APIRouter(prefix="/api/v1")
    current = Project(initial) if initial else None

    services = {}

    def service():
        item = project()
        if item.metadata["id"] not in services:
            services[item.metadata["id"]] = SegmentationService(item)
        return services[item.metadata["id"]]

    def project() -> Project:
        if current is None:
            raise HTTPException(409, "Open a project first")
        return current

    @router.post("/project/open")
    def open_project(body: OpenProject):
        nonlocal current
        replacement = Project(Path(body.path))
        current = replacement
        return {**current.metadata, "root": str(current.root), "image_count": len(current.entries)}

    @router.get("/project")
    def get_project():
        item = project()
        return {**item.metadata, "root": str(item.root), "image_count": len(item.entries)}

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

    @router.post("/images/{image_id}/segment")
    def segment(image_id: str, body: SegmentRequest):
        item = service()
        return item.executor.submit(item.process, image_id, body).result()

    @router.post("/jobs")
    def create_job(body: SegmentRequest):
        item = service()
        job_id = uid()
        job = {
            "id": job_id,
            "status": "running",
            "completed": 0,
            "failed": [],
            "total": len(item.project.entries),
            "cancel": False,
        }
        item.jobs[job_id] = job

        def run():
            for image_id in list(item.project.entries):
                if job["cancel"]:
                    break
                try:
                    item.executor.submit(item.process, image_id, body).result()
                except Exception as error:
                    job["failed"].append({"image": image_id, "error": str(error)})
                job["completed"] += 1
            job["status"] = "cancelled" if job["cancel"] else "complete"

        threading.Thread(target=run, daemon=True).start()
        return job

    @router.get("/jobs/{job_id}")
    def get_job(job_id: str):
        return service().jobs[job_id]

    @router.delete("/jobs/{job_id}")
    def cancel_job(job_id: str):
        job = service().jobs[job_id]
        job["cancel"] = True
        return job

    # Keep access local to this application instance rather than a module global.
    router.project = project
    return router
