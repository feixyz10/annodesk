import time

from annodesk.lifecycle import restore_trash, trash_excluded
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
    ann.detection_review = "uncertain"
    project.save(ids[0], ann)
    ann = project.annotation(ids[1])
    ann.segmentation_review, ann.excluded = "ok", True
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
