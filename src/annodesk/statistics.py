"""Rebuildable review metadata index. Never imports YOLO labels or loads pixels."""

import json
import sqlite3
import threading
from contextlib import closing


class StatisticsIndex:
    def __init__(self, project):
        self.project = project
        self.lock = threading.RLock()
        self.status = "indexing"
        self.revision = 0
        self.dirty = True
        self.building = False
        self.refresh()

    def refresh(self):
        with self.lock:
            self.dirty = True
            self.status = "indexing"
            if self.building:
                return
            self.building = True
        threading.Thread(target=self._build, daemon=True, name="annodesk-statistics").start()

    def _scan(self):
        with closing(sqlite3.connect(self.project.private / "statistics.sqlite3")) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS reviews (id TEXT PRIMARY KEY, detection TEXT, segmentation TEXT, excluded INTEGER, stamp TEXT)"
            )
            known = {r[0]: r[1] for r in db.execute("SELECT id, stamp FROM reviews")}
            for image_id in self.project.entries:
                path = self.project.annotation_path(image_id)
                stat = path.stat() if path.exists() else None
                stamp = f"{stat.st_mtime_ns}:{stat.st_size}" if stat else "missing"
                if known.get(image_id) == stamp:
                    continue
                record = json.loads(path.read_text()) if stat else {}
                db.execute(
                    "INSERT OR REPLACE INTO reviews VALUES (?,?,?,?,?)",
                    (
                        image_id,
                        record.get("detection_review", "pending"),
                        record.get("segmentation_review", "pending"),
                        bool(record.get("excluded")),
                        stamp,
                    ),
                )
            for image_id in known.keys() - self.project.entries.keys():
                db.execute("DELETE FROM reviews WHERE id=?", (image_id,))

    def _build(self):
        try:
            with self.project.lock, self.lock:
                for attempt in range(2):
                    try:
                        self._scan()
                        break
                    except sqlite3.DatabaseError:
                        if attempt:
                            raise
                        # This is derived data only. Connections are closed before replacement.
                        path = self.project.private / "statistics.sqlite3"
                        for suffix in ("", "-journal", "-wal", "-shm"):
                            path.with_name(path.name + suffix).unlink(missing_ok=True)
                self.revision += 1
                self.status = "ready"
                self.dirty = False
        except (OSError, ValueError, sqlite3.Error):
            self.status = "indexing"
            self.dirty = True
        finally:
            with self.lock:
                self.building = False

    def update(self, image_id, annotation):
        with self.lock:
            if self.status != "ready":
                self.refresh()
                return
            try:
                stat = self.project.annotation_path(image_id).stat()
                with (
                    closing(sqlite3.connect(self.project.private / "statistics.sqlite3")) as db,
                    db,
                ):
                    db.execute(
                        "INSERT OR REPLACE INTO reviews VALUES (?,?,?,?,?)",
                        (
                            image_id,
                            annotation.detection_review,
                            annotation.segmentation_review,
                            annotation.excluded,
                            f"{stat.st_mtime_ns}:{stat.st_size}",
                        ),
                    )
                self.revision += 1
            except (OSError, sqlite3.Error):
                self.refresh()

    def read(self, task):
        with self.lock:
            if self.dirty and not self.building:
                self.refresh()
            counts = dict.fromkeys(("pending", "ok", "uncertain", "excluded"), 0)
            if self.status == "ready":
                try:
                    with closing(
                        sqlite3.connect(self.project.private / "statistics.sqlite3")
                    ) as db:
                        column = {"detection": "detection", "segmentation": "segmentation"}[task]
                        for state, excluded, count in db.execute(
                            f"SELECT {column}, excluded, COUNT(*) FROM reviews GROUP BY {column}, excluded"
                        ):
                            counts["excluded" if excluded else state] += count
                except (sqlite3.Error, OSError, KeyError):
                    self.refresh()
                    counts = dict.fromkeys(counts, 0)
            return {
                "total": len(self.project.entries),
                "counts": counts,
                "reviewed": counts["ok"] + counts["uncertain"] + counts["excluded"],
                "statistics_revision": self.revision,
                "status": self.status,
            }
