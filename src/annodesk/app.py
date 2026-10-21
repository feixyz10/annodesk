"""Application factory for combined, API-only and UI-only deployment."""

from pathlib import Path
from typing import Literal

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from annodesk import __version__


def create_app(
    mode: Literal["serve", "api", "ui"] = "serve",
    api_url: str = "",
    project: Path | None = None,
) -> FastAPI:
    app = FastAPI(title="AnnoDesk", version=__version__)
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )
    if mode != "ui":

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
            "/", StaticFiles(directory=Path(__file__).parent / "web_dist", html=True), name="web"
        )
    return app
