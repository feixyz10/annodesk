import time

import numpy as np

from annodesk.lifecycle import restore_trash, trash_excluded
from annodesk.masks import encode_mask
from annodesk.statistics import StatisticsIndex
from annodesk.storage import Project
from tests.test_batch import dataset


def ready(index, task="segmentation"):
    for _ in range(100):
        value = index.read(task)
        if value["status"] == "ready":
            return value
        time.sleep(0.01)
    raise AssertionError("Statistics never became ready")


def test_statistics_is_read_only_and_excluded_wins(tmp_path):
    dataset(tmp_path, count=3)
    project = Project(tmp_path)
    project.statistics = index = StatisticsIndex(project)
    assert ready(index)["counts"]["pending"] == 3
    assert not list((project.private / "annotations").glob("*.json"))
    ids = list(project.entries)
    ann = project.annotation(ids[0])
    ann.segmentation_review = "ok"
    ann.explicit_empty["segmentation"] = True
    ann.detection_review = "uncertain"
    project.save(ids[0], ann)
    ann = project.annotation(ids[1])
    ann.segmentation_review, ann.excluded = "ok", True
    ann.explicit_empty["segmentation"] = True
    project.save(ids[1], ann)
    result = ready(index)
    assert result["counts"] == {"pending": 1, "ok": 1, "uncertain": 0, "excluded": 1}
    assert result["reviewed"] == 2
    assert ready(index, "detection")["counts"]["uncertain"] == 1
    operation = trash_excluded(project)
    assert ready(index)["total"] == 2
    restore_trash(project, operation)
    assert ready(index)["total"] == 3
    assert ready(index)["counts"]["excluded"] == 1


def test_corrupt_derived_database_is_rebuilt_without_touching_annotations(tmp_path):
    dataset(tmp_path)
    project = Project(tmp_path)
    image_id = next(iter(project.entries))
    annotation = project.annotation(image_id)
    annotation.segmentation_review = "ok"
    annotation.explicit_empty["segmentation"] = True
    project.save(image_id, annotation)
    original = project.annotation_path(image_id).read_bytes()
    cache = project.private / "statistics.sqlite3"
    cache.write_bytes(b"broken database")
    project.statistics = index = StatisticsIndex(project)
    assert ready(index)["counts"]["ok"] == 1
    cache.write_bytes(b"broken again after ready")
    assert index.read("segmentation")["status"] == "indexing"
    assert ready(index)["counts"]["ok"] == 1
    assert project.annotation_path(image_id).read_bytes() == original


def test_imported_boxes_and_polygons_are_counted_without_images_or_materialization(
    tmp_path, monkeypatch
):
    dataset(tmp_path, count=2)
    (tmp_path / "labels_seg/train/nested").mkdir(parents=True)
    (tmp_path / "labels_seg/train/nested/0.txt").write_text("2 0.1 0.1 0.8 0.1 0.8 0.8\n")
    project = Project(tmp_path)

    def no_image(*args, **kwargs):
        raise AssertionError("Statistics must not open images or materialize annotations")

    monkeypatch.setattr(project, "image_size", no_image)
    monkeypatch.setattr(project, "annotation", no_image)
    project.statistics = index = StatisticsIndex(project)
    result = ready(index)
    assert (result["boxes"], result["masks"], result["instances"]) == (2, 1, 3)
    row = next(c for c in result["classes"] if c["index"] == 2)
    assert (row["images"], row["boxes"], row["masks"]) == (2, 2, 1)
    assert not list((project.private / "annotations").glob("*.json"))


def test_geometry_updates_count_masks_once_skip_prompts_and_filter_excluded(tmp_path):
    from annodesk.domain import Instance

    dataset(tmp_path, count=2)
    project = Project(tmp_path)
    category = project.metadata["classes"][0]["id"]
    ids = list(project.entries)
    ann = project.annotation(ids[0])
    binary = np.zeros((20, 30), dtype=np.uint8)
    binary[1:4, 1:4] = 1
    ann.instances[0].mask = encode_mask(binary)
    ann.instances[0].prompt_box = [1, 1, 3, 3]
    ann = project.save(ids[0], ann)
    excluded = project.annotation(ids[1])
    excluded.excluded = True
    project.save(ids[1], excluded)
    project.statistics = index = StatisticsIndex(project)
    result = ready(index)
    assert (result["boxes"], result["masks"]) == (1, 1)
    assert index.read("detection", True)["boxes"] == 2
    assert result["counts"]["excluded"] == 1
    ann.instances = [Instance(class_id=category, prompt_box=[1, 1, 3, 3])]
    project.save(ids[0], ann)
    result = index.read("segmentation")
    assert (result["boxes"], result["masks"], result["instances"]) == (0, 0, 1)


def test_invalid_imports_are_reported_and_refresh_after_label_change(tmp_path):
    dataset(tmp_path)
    label = tmp_path / "labels/train/nested/0.txt"
    label.write_text("2 0.1 0.5 0.8 0.5\n")
    project = Project(tmp_path)
    project.statistics = index = StatisticsIndex(project)
    result = ready(index)
    assert result["invalid_images"] == 1 and result["boxes"] == 0
    label.write_text("2 0.5 0.5 0.4 0.4\n")
    index.refresh()
    result = ready(index)
    assert result["invalid_images"] == 0 and result["boxes"] == 1


def test_legacy_review_cache_gets_geometry_counts_without_materialization(tmp_path):
    import sqlite3

    dataset(tmp_path)
    project = Project(tmp_path)
    with sqlite3.connect(project.private / "statistics.sqlite3") as db:
        db.execute(
            "CREATE TABLE reviews (id TEXT PRIMARY KEY, detection TEXT, segmentation TEXT, excluded INTEGER, stamp TEXT)"
        )
    project.statistics = index = StatisticsIndex(project)
    result = ready(index)
    assert result["boxes"] == 1 and result["masks"] == 0
    assert not list((project.private / "annotations").glob("*.json"))
