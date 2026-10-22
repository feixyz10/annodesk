"""Session logs: parent-owned Loguru sinks and a bounded UI event history."""

import json
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from loguru import logger

LEVELS = {
    "TRACE": 5,
    "DEBUG": 10,
    "INFO": 20,
    "SUCCESS": 25,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}


class EventLog:
    def __init__(self, directory: Path | None = None, level: str = "INFO", *, files: bool = False):
        self.session_id = str(uuid4())
        self.sequence = 0
        self.events = deque(maxlen=2000)
        self.lock = threading.RLock()
        self.path = None
        self.sink = None
        self.repeats = {}
        if level.upper() not in LEVELS:
            raise ValueError("Unknown log level")
        if files:
            folder = (directory or Path("~/.cache/annodesk")).expanduser()
            try:
                folder.mkdir(parents=True, exist_ok=True)
                # Only remove application session files matching our exact naming convention.
                for old in folder.glob("????-??-??_??????_??????*.log*"):
                    if old.is_file() and old.stat().st_mtime < time.time() - 14 * 86400:
                        old.unlink()
                path = folder / f"{datetime.now():%Y-%m-%d_%H%M%S_%f}.log"
                path.touch(exist_ok=False)
                self.path = path
                self.sink = logger.add(
                    path,
                    level=level.upper(),
                    rotation="20 MB",
                    retention="14 days",
                    encoding="utf-8",
                    colorize=False,
                    diagnose=False,
                    backtrace=False,
                    format="{time:YYYY-MM-DD HH:mm:ss.SSS ZZ} | {level: <8} | {message}",
                    filter=lambda record: record["extra"].get("session_id") == self.session_id,
                )
            except OSError as error:
                self.emit("WARNING", f"File logging unavailable: {error}", event_type="logging")

    def bind(self, **context):
        return BoundEvents(self, context)

    def close(self):
        self.flush_repeats(force=True)
        if self.sink is not None:
            logger.remove(self.sink)
            self.sink = None

    def _append(self, level, message, fields):
        self.sequence += 1
        self.events.append(
            {
                "session_id": self.session_id,
                "sequence": self.sequence,
                "timestamp": datetime.now().astimezone().isoformat(),
                "level_name": level,
                "level_no": LEVELS[level],
                "message": message[:2000],
                "truncated": len(message) > 2000,
                "event_type": fields.get("event_type", "service"),
                **{k: fields.get(k) for k in ("project_id", "job_id", "worker_id", "device")},
                "repeat_count": fields.get("repeat_count", 0),
            }
        )

    def emit(self, level: str, message: str, *, ui_visible: bool = True, **fields):
        level = level.upper()
        logger.bind(session_id=self.session_id).opt(exception=fields.pop("_exception", None)).log(
            level, message
        )
        if not ui_visible or LEVELS[level] < 20:
            return
        with self.lock:
            key = None
            if LEVELS[level] >= 40:
                key = tuple(
                    fields.get(k) for k in ("project_id", "job_id", "event_type", "error_code")
                )
                key += (level,)
            if key and key in self.repeats:
                item = self.repeats[key]
                item["count"] += 1
                return
            self._append(level, message, fields)
            if key:
                self.repeats[key] = {
                    "at": time.monotonic(),
                    "count": 0,
                    "level": level,
                    "message": message,
                    "fields": fields,
                }
            self.flush_repeats()

    def flush_repeats(self, force=False):
        with self.lock:
            for key, item in list(self.repeats.items()):
                if force or time.monotonic() - item["at"] >= 10:
                    if item["count"]:
                        self._append(
                            item["level"],
                            f"{item['count']} additional occurrences: {item['message']}",
                            {**item["fields"], "repeat_count": item["count"]},
                        )
                    del self.repeats[key]

    def read(
        self,
        cursor: str = "",
        level: int = 20,
        comparison: str = "gte",
        project_id: str = "",
        limit: int = 200,
    ):
        self.flush_repeats()
        with self.lock:
            session, _, number = cursor.partition(":")
            try:
                after = int(number) if session == self.session_id else 0
            except ValueError:
                after = 0
            gap = bool(cursor) and (
                session != self.session_id
                or (self.events and after < self.events[0]["sequence"] - 1)
            )
            matches = [
                e
                for e in self.events
                if e["sequence"] > after
                and (e["level_no"] == level if comparison == "eq" else e["level_no"] >= level)
                and (not project_id or e["project_id"] in (None, project_id))
            ]
            return {
                "session_id": self.session_id,
                "items": matches[-limit:],
                "next_cursor": f"{self.session_id}:{self.sequence}",
                "gap": gap or len(matches) > limit,
            }


class BoundEvents:
    def __init__(self, parent, context):
        self.parent, self.context = parent, context

    def emit(self, level, message, **fields):
        self.parent.emit(level, message, **{**self.context, **fields})


def log_routes(events: EventLog) -> APIRouter:
    router = APIRouter(prefix="/api/v1/logs")

    @router.get("")
    def recent(
        cursor: str = "",
        level: int = Query(20, ge=20, le=50),
        comparison: str = Query("gte", pattern="^(eq|gte)$"),
        project_id: str = "",
        limit: int = Query(200, ge=1, le=500),
    ):
        return events.read(cursor, level, comparison, project_id, limit)

    @router.get("/download")
    def download():
        if events.path is None:
            raise ValueError("File logging is unavailable for this session")
        return FileResponse(events.path, filename=events.path.name, media_type="text/plain")

    @router.get("/stream")
    async def stream(
        request: Request,
        cursor: str = "",
        level: int = Query(20, ge=20, le=50),
        comparison: str = Query("gte", pattern="^(eq|gte)$"),
        project_id: str = "",
    ):
        import asyncio

        async def generate():
            after = cursor
            heartbeat = time.monotonic()
            while not await request.is_disconnected():
                page = events.read(after, level, comparison, project_id, 500)
                if page["items"] or page["gap"] or page["next_cursor"] != after:
                    yield f"data: {json.dumps(page)}\n\n"
                    after = page["next_cursor"]
                if time.monotonic() - heartbeat >= 15:
                    yield ": heartbeat\n\n"
                    heartbeat = time.monotonic()
                await asyncio.sleep(0.5)

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
        )

    return router
