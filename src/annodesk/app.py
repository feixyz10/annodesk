"""Application factory for combined, API-only and UI-only deployment."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from annodesk import __version__
from annodesk.events import EventLog, log_routes
from annodesk.storage import RevisionConflict


class WorkbenchFiles(StaticFiles):
    """Never reuse entry HTML across builds, including conditional requests."""

    def file_response(self, full_path, stat_result, scope, status_code=200):
        if Path(full_path).suffix.lower() == ".html":
            response = FileResponse(
                full_path,
                status_code=status_code,
                stat_result=stat_result,
                headers={"Cache-Control": "no-store"},
            )
            # Avoid 304 responses that keep a browser's old asset manifest alive.
            for name in ("etag", "last-modified"):
                if name in response.headers:
                    del response.headers[name]
            return response
        return super().file_response(full_path, stat_result, scope, status_code)


def create_app(
    mode: Literal["serve", "api", "ui"] = "serve",
    api_url: str = "",
    project: Path | None = None,
    models_config: Path | None = None,
    events: EventLog | None = None,
) -> FastAPI:
    events = events or EventLog()
    router = None

    @asynccontextmanager
    async def lifespan(_app):
        try:
            yield
        finally:
            if router:
                router.close()
            events.close()

    app = FastAPI(title="AnnoDesk", version=__version__, lifespan=lifespan)
    app.state.events = events
    app.include_router(log_routes(events))
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )

    @app.middleware("http")
    async def fresh_json(request: Request, call_next):
        response = await call_next(request)
        if response.headers.get("content-type", "").startswith("application/json"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ValueError)
    async def invalid(_request: Request, error: ValueError):
        events.emit("WARNING", str(error), event_type="request_error")
        return JSONResponse(
            {"detail": str(error)}, status_code=409 if isinstance(error, RevisionConflict) else 400
        )

    @app.exception_handler(KeyError)
    async def missing(_request: Request, error: KeyError):
        return JSONResponse({"detail": str(error)}, status_code=404)

    if mode != "ui":
        from annodesk.routes import project_routes

        router = project_routes(project, models_config, events)
        app.include_router(router)

        @app.get("/api/v1/info")
        def info():
            return {"version": __version__, "protocol": 1, "name": "AnnoDesk"}

    if mode != "api":

        @app.get("/ui-config.json")
        def ui_config():
            base = api_url.rstrip("/")
            return JSONResponse(
                {"apiBase": f"{base}/api/v1"}, headers={"Cache-Control": "no-store"}
            )

        app.mount(
            "/", WorkbenchFiles(directory=Path(__file__).parent / "web_dist", html=True), name="web"
        )
    return app
