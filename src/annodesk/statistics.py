"""Disposable review and annotation counts; never decodes images or masks."""

import hashlib
import json
import math
import sqlite3
import threading
from collections import defaultdict
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

    @staticmethod
    def _stamp(path):
        stat = path.stat() if path.exists() else None
        return f"{stat.st_mtime_ns}:{stat.st_size}" if stat else "missing"

    def _imported(self, image_id):
        """Count normalized YOLO records without materialization or pixel IO."""
        classes = {c["index"]: c["id"] for c in self.project.metadata["classes"]}
        instances = []
        for segmentation in (False, True):
            path = self.project.label_path(image_id, segmentation)
            if not path.exists():
                continue
            for line in path.read_text().splitlines():
                if not line.strip():
                    continue
                parts = line.split()
                category = classes[int(parts[0])]
                coords = [float(v) for v in parts[1:]]
                if any(not math.isfinite(v) or not 0 <= v <= 1 for v in coords):
                    raise ValueError("Invalid normalized coordinates")
                if segmentation:
                    if len(coords) < 6 or len(coords) % 2:
                        raise ValueError("Invalid polygon")
                else:
                    if len(coords) != 4:
                        raise ValueError("Invalid detection box")
                    x, y, width, height = coords
                    if (
                        width <= 0
                        or height <= 0
                        or min(x - width / 2, y - height / 2) < -1e-6
                        or max(x + width / 2, y + height / 2) > 1 + 1e-6
                    ):
                        raise ValueError("Box outside image")
                instances.append(
                    {
                        "class_id": category,
                        "polygons": [coords] if segmentation else [],
                        "box": None if segmentation else coords,
                    }
                )
        return {"instances": instances}

    @staticmethod
    def _counts(record):
        counts = defaultdict(lambda: [0, 0, 0])
        for obj in record.get("instances", []):
            category = obj.get("class_id") or ""
            count = counts[category]
            count[0] += bool(obj.get("box"))
            count[1] += bool(obj.get("mask") or obj.get("polygons"))
            count[2] += 1
        return counts

    def _write_counts(self, db, image_id, record, stamp, invalid=0):
        counts = self._counts(record)
        db.execute("DELETE FROM annotation_counts WHERE image_id=?", (image_id,))
        db.executemany(
            "INSERT INTO annotation_counts VALUES (?,?,?,?,?)",
            [(image_id, category, *values) for category, values in counts.items()],
        )
        db.execute("INSERT OR REPLACE INTO count_stamps VALUES (?,?,?)", (image_id, stamp, invalid))

    def _scan(self):
        with closing(sqlite3.connect(self.project.private / "statistics.sqlite3")) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS reviews (id TEXT PRIMARY KEY, detection TEXT, segmentation TEXT, excluded INTEGER, stamp TEXT)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS annotation_counts (image_id TEXT, class_id TEXT, boxes INTEGER, masks INTEGER, instances INTEGER, PRIMARY KEY(image_id,class_id))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS count_stamps (id TEXT PRIMARY KEY, stamp TEXT, invalid INTEGER)"
            )
            known = dict(db.execute("SELECT id, stamp FROM reviews"))
            known_counts = dict(db.execute("SELECT id, stamp FROM count_stamps"))
            mapping = hashlib.sha256(
                json.dumps(
                    [(c["index"], c["id"]) for c in self.project.metadata["classes"]]
                ).encode()
            ).hexdigest()
            for image_id in self.project.entries:
                path = self.project.annotation_path(image_id)
                stamp = self._stamp(path)
                geometry_stamp = (
                    stamp
                    if stamp != "missing"
                    else json.dumps(
                        [
                            self._stamp(self.project.label_path(image_id, seg))
                            for seg in (False, True)
                        ]
                        + [mapping]
                    )
                )
                if known.get(image_id) == stamp and known_counts.get(image_id) == geometry_stamp:
                    continue
                record = {}
                invalid = 0
                try:
                    record = (
                        json.loads(path.read_text())
                        if stamp != "missing"
                        else self._imported(image_id)
                    )
                    self._counts(record)
                except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError):
                    record, invalid = {}, 1
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
                self._write_counts(db, image_id, record, geometry_stamp, invalid)
            for image_id in (known.keys() | known_counts.keys()) - self.project.entries.keys():
                for table, column in (
                    ("reviews", "id"),
                    ("annotation_counts", "image_id"),
                    ("count_stamps", "id"),
                ):
                    db.execute(f"DELETE FROM {table} WHERE {column}=?", (image_id,))

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
                stamp = self._stamp(self.project.annotation_path(image_id))
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
                            stamp,
                        ),
                    )
                    self._write_counts(db, image_id, annotation.model_dump(), stamp)
                self.revision += 1
            except (OSError, sqlite3.Error):
                self.refresh()

    def read(self, task, include_excluded=False):
        with self.project.lock, self.lock:
            if self.dirty and not self.building:
                self.refresh()
            counts = dict.fromkeys(("pending", "ok", "uncertain", "excluded"), 0)
            rows = []
            invalid = 0
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
                        where = "" if include_excluded else " WHERE r.excluded=0"
                        rows = list(
                            db.execute(
                                "SELECT c.class_id,SUM(c.boxes),SUM(c.masks),SUM(c.instances),COUNT(*) FROM annotation_counts c JOIN reviews r ON r.id=c.image_id"
                                + where
                                + " GROUP BY c.class_id"
                            )
                        )
                        invalid = db.execute(
                            "SELECT COALESCE(SUM(c.invalid),0) FROM count_stamps c JOIN reviews r ON r.id=c.id"
                            + where
                        ).fetchone()[0]
                except (sqlite3.Error, OSError, KeyError):
                    self.refresh()
                    counts, rows, invalid = dict.fromkeys(counts, 0), [], 0
            categories = {
                c["id"]: {
                    "class_id": c["id"],
                    "index": c["index"],
                    "name": c["name"],
                    "color": c["color"],
                    "boxes": 0,
                    "masks": 0,
                    "instances": 0,
                    "images": 0,
                }
                for c in self.project.metadata["classes"]
            }
            for category, boxes, masks, instances, images in rows:
                item = categories.setdefault(
                    category,
                    {"class_id": category or None, "index": None, "name": None, "color": "#657286"},
                )
                item.update(boxes=boxes, masks=masks, instances=instances, images=images)
            return {
                "total": len(self.project.entries),
                "counts": counts,
                "reviewed": counts["ok"] + counts["uncertain"] + counts["excluded"],
                "statistics_revision": self.revision,
                "status": self.status,
                "boxes": sum(r[1] for r in rows),
                "masks": sum(r[2] for r in rows),
                "instances": sum(r[3] for r in rows),
                "classes": list(categories.values()),
                "include_excluded": include_excluded,
                "invalid_images": invalid,
            }
