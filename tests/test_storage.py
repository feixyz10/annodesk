from pathlib import Path

import pytest
from PIL import Image

from annodesk.domain import Annotation, Instance
from annodesk.storage import Project, RevisionConflict


def dataset(tmp_path: Path):
    images = tmp_path / "images" / "train" / "camera"
    images.mkdir(parents=True)
    Image.new("RGB", (100, 80)).save(images / "a.png")
    labels = tmp_path / "labels" / "train" / "camera"
    labels.mkdir(parents=True)
    (labels / "a.txt").write_text("2 0.5 0.5 0.4 0.5\n")
    return tmp_path


def test_failed_transaction_keeps_journal_until_restart(tmp_path, monkeypatch):
    import json

    from annodesk import storage

    project = Project(dataset(tmp_path))
    image_id = project.images()[0]["id"]
    ann = project.annotation(image_id)
    original_write = storage.atomic_write

    def fail_label(path, text):
        if path == project.label_path(image_id):
            raise OSError("Label write failed")
        original_write(path, text)

    ann.instances[0].box = [10, 10, 50, 50]
    with monkeypatch.context() as patcher:
        patcher.setattr(storage, "atomic_write", fail_label)
        with pytest.raises(OSError):
            project.save(image_id, ann)
    journal = project.private / "pending.json"
    before = journal.read_text()
    with pytest.raises(RevisionConflict, match="restart"):
        project.add_category("Must not overwrite recovery")
    from annodesk.lifecycle import export_project, reindex_classes, trash_excluded

    for operation in (export_project, trash_excluded, reindex_classes):
        with pytest.raises(RevisionConflict, match="restart"):
            operation(project)
    assert journal.read_text() == before
    recovered = Project(tmp_path)
    recovered.validate_fingerprints(image_id)
    assert recovered.annotation(image_id).instances[0].box == [10, 10, 50, 50]
    assert not journal.exists()
    assert "Must not overwrite recovery" not in json.dumps(recovered.metadata)


@pytest.mark.parametrize(
    "geometry",
    [
        {"box": [0, 0, 200, 100]},
        {"prompt_box": [-1, 0, 20, 20]},
        {"mask": {"size": [80, 100], "counts": "\uffff"}},
        {"polygons": [[[0, 0], [200, 0], [0, 100]]]},
        {"mask": {"size": [2, 2], "counts": "invalid"}},
    ],
)
def test_unassigned_drafts_still_validate_geometry(tmp_path, geometry):
    project = Project(dataset(tmp_path))
    image_id = project.images()[0]["id"]
    ann = project.annotation(image_id)
    ann.instances = [Instance(class_id=None, **geometry)]
    with pytest.raises(ValueError):
        project.save(image_id, ann)
    assert project.annotation(image_id).revision == 0


def test_valid_unassigned_draft_remains_editable_without_yolo_projection(tmp_path):
    project = Project(dataset(tmp_path))
    image_id = project.images()[0]["id"]
    ann = project.annotation(image_id)
    ann.instances = [Instance(box=[1, 1, 8, 8])]
    saved = project.save(image_id, ann)
    assert saved.instances[0].class_id is None
    assert project.label_path(image_id).read_text() == ""
    saved.instances[0].class_id = project.metadata["classes"][0]["id"]
    project.save(image_id, saved)
    assert project.label_path(image_id).read_text().startswith("2 ")


def test_import_save_and_clear(tmp_path):
    project = Project(dataset(tmp_path))
    item = project.images()[0]
    ann = project.annotation(item["id"])
    assert ann.instances[0].box == [30, 20, 70, 60]
    assert next(c for c in project.metadata["classes"] if c["index"] == 2)["name"] == "class_2"
    saved = project.save(item["id"], ann)
    assert saved.revision == 1
    with pytest.raises(RevisionConflict):
        project.save(item["id"], ann)
    saved.instances = []
    project.save(item["id"], saved)
    assert (tmp_path / "labels/train/camera/a.txt").read_text() == ""
    assert Project(tmp_path).annotation(item["id"]).instances == []


def test_mask_only_does_not_create_box(tmp_path):
    project = Project(dataset(tmp_path))
    item = project.images()[0]
    ann = project.annotation(item["id"])
    ann.instances = [
        Instance(class_id=ann.instances[0].class_id, polygons=[[[1, 1], [8, 1], [8, 8]]])
    ]
    project.save(item["id"], ann)
    assert (tmp_path / "labels/train/camera/a.txt").read_text() == ""
    assert (tmp_path / "labels_seg/train/camera/a.txt").read_text().startswith("2 ")


def test_duplicate_stem_rejected(tmp_path):
    root = dataset(tmp_path)
    Image.new("RGB", (100, 80)).save(root / "images/train/camera/a.jpg")
    with pytest.raises(ValueError, match="same label"):
        Project(root)


def test_invalid_geometry_rejected(tmp_path):
    project = Project(dataset(tmp_path))
    ann = Annotation(instances=[Instance(class_id="missing", box=[0, 0, 20, 10])])
    with pytest.raises(ValueError, match="class"):
        project.save(project.images()[0]["id"], ann)
    with pytest.raises(ValueError):
        Instance(class_id="x", box=[float("nan"), 0, 20, 10])


def test_mismatched_mask_dimensions_rejected(tmp_path):
    import numpy as np

    from annodesk.masks import encode_mask

    project = Project(dataset(tmp_path))
    image_id = project.images()[0]["id"]
    ann = project.annotation(image_id)
    ann.instances[0].mask = encode_mask(np.ones((2, 2), dtype=np.uint8))
    with pytest.raises(ValueError, match="mask"):
        project.save(image_id, ann)


def test_yolo_rounding_at_image_edges_is_clipped_but_overflow_rejected(tmp_path):
    root = dataset(tmp_path)
    (root / "labels/train/camera/a.txt").write_text("2 0.092344 0.5 0.1846884 1\n")
    project = Project(root)
    image_id = project.images()[0]["id"]
    imported = project.annotation(image_id)
    assert imported.instances[0].box[0] == 0
    assert (root / "labels/train/camera/a.txt").read_text() == "2 0.092344 0.5 0.1846884 1\n"
    saved = project.save(image_id, imported)
    assert saved.instances[0].box[0] == 0
    assert Project(root).annotation(image_id).instances[0].box[0] == 0
    saved.instances[0].box[0] = -0.01
    with pytest.raises(ValueError, match="Box outside image"):
        project.save(image_id, saved)


def test_rounding_tolerance_does_not_allow_a_degenerate_clipped_box(tmp_path):
    project = Project(dataset(tmp_path))
    image_id = project.images()[0]["id"]
    ann = project.annotation(image_id)
    ann.instances[0].box = [-0.00005, 1, -0.00001, 5]
    with pytest.raises(ValueError, match="Box outside image"):
        project.save(image_id, ann)


def test_mask_is_authoritative_over_missing_or_stale_polygons(tmp_path):
    import numpy as np

    from annodesk.masks import encode_mask

    project = Project(dataset(tmp_path))
    image_id = project.images()[0]["id"]
    ann = project.annotation(image_id)
    binary = np.zeros((80, 100), dtype=np.uint8)
    binary[5:10, 6:12] = 1
    ann.instances[0].mask = encode_mask(binary)
    saved = project.save(image_id, ann)
    assert saved.instances[0].polygons
    assert project.label_path(image_id, True).read_text().strip()
    saved.instances[0].polygons = [[[60, 50], [80, 50], [80, 70]]]
    saved = project.save(image_id, saved)
    assert max(x for polygon in saved.instances[0].polygons for x, _ in polygon) == 12


def test_save_repairs_legacy_polygon_cache_even_when_rle_is_unchanged(tmp_path):
    import json

    import numpy as np

    from annodesk.masks import encode_mask

    project = Project(dataset(tmp_path))
    image_id = project.images()[0]["id"]
    ann = project.annotation(image_id)
    binary = np.zeros((80, 100), dtype=np.uint8)
    binary[5:10, 6:12] = 1
    ann.instances[0].mask = encode_mask(binary)
    saved = project.save(image_id, ann)
    # Older records can contain an incorrect cached polygon for an unchanged mask.
    path = project.annotation_path(image_id)
    record = json.loads(path.read_text())
    record["instances"][0]["polygons"] = [[[60, 50], [80, 50], [80, 70]]]
    path.write_text(json.dumps(record))
    saved = project.save(image_id, project.annotation(image_id))
    assert max(x for polygon in saved.instances[0].polygons for x, _ in polygon) == 12


@pytest.mark.parametrize("materialize", [False, True])
@pytest.mark.parametrize(
    "coordinates",
    [
        "0.1 0.5 0.8 0.5",  # left
        "0.9 0.5 0.8 0.5",  # right
        "0.5 0.1 0.5 0.8",  # top
        "0.5 0.9 0.5 0.8",  # bottom
        "0.5 0.5 0 0.5",  # zero width
        "0.5 0.5 0.5 0",  # zero height
    ],
)
def test_import_rejects_actual_invalid_bounds_before_materializing(
    tmp_path, coordinates, materialize
):
    root = dataset(tmp_path)
    label = root / "labels/train/camera/a.txt"
    original = f"2 0.5 0.5 0.4 0.5\n\n2 {coordinates}\n"
    label.write_text(original)
    project = Project(root)
    image_id = project.images()[0]["id"]
    with pytest.raises(ValueError) as error:
        project.annotation(image_id, materialize=materialize)
    assert f"{label}:3: Box outside image" in str(error.value)
    assert not project.annotation_path(image_id).exists()
    assert label.read_text() == original
    # Correcting the source file is sufficient; no invalid internal revision was cached.
    label.write_text("2 0.5 0.5 1 1\n")
    annotation = project.annotation(image_id)
    assert annotation.instances[0].box == [0, 0, 100, 80]
    annotation.notes = "Imported bounds are editable"
    project.save(image_id, annotation)


def test_first_materialization_serializes_with_successful_human_save(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    project = Project(dataset(tmp_path))
    image_id = project.images()[0]["id"]
    initial_entered, release, saving, saved = Event(), Event(), Event(), Event()
    original_initial = project._write_initial
    first = True

    def paused_initial(image_id, annotation):
        nonlocal first
        if first:
            first = False
            initial_entered.set()
            assert release.wait(5)
        return original_initial(image_id, annotation)

    monkeypatch.setattr(project, "_write_initial", paused_initial)
    human = Annotation(
        notes="Human save must survive",
        instances=[Instance(class_id=project.metadata["classes"][0]["id"], box=[10, 10, 50, 50])],
    )

    def human_save():
        saving.set()
        result = project.save(image_id, human)
        saved.set()
        return result

    with ThreadPoolExecutor(max_workers=2) as executor:
        read = executor.submit(project.annotation, image_id)
        try:
            assert initial_entered.wait(5)
            write = executor.submit(human_save)
            assert saving.wait(5)
            assert not saved.wait(0.1), "Writer passed a first reader still materializing"
        finally:
            release.set()
        read.result(timeout=5)
        assert write.result(timeout=5).revision == 1
    current = project.annotation(image_id)
    assert current.revision == 1
    assert current.notes == "Human save must survive"
    assert current.instances[0].box == [10, 10, 50, 50]
    project.validate_fingerprints(image_id)


def test_late_initializer_returns_committed_record_without_overwriting_it(tmp_path):
    project = Project(dataset(tmp_path))
    image_id = project.images()[0]["id"]
    stale = project.annotation(image_id, materialize=False)
    human = stale.model_copy(deep=True)
    human.notes = "Committed before late initialization"
    human.instances[0].box = [10, 10, 50, 50]
    committed = project.save(image_id, human)
    path = project.annotation_path(image_id)
    before = path.read_bytes()
    returned = project._write_initial(image_id, stale)
    assert returned.model_dump() == committed.model_dump()
    assert path.read_bytes() == before
    project.validate_fingerprints(image_id)
