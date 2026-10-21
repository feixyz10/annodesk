# AnnoDesk

A local-first image annotation workbench for YOLO boxes and instance masks.
The full product design is in [docs/specs/annodesk.md](docs/specs/annodesk.md).
This repository contains the first implementation; the specification also describes
features that are still pending.

## Run

Python 3.11+ and uv are required (the repository uses Python 3.13).

```sh
uv sync
uv run annodesk serve --project /absolute/path/to/dataset --open
```

The dataset may contain `images/` or be an image directory itself. Images are indexed
recursively. Existing YOLO detection labels are read from `labels/`, segmentation
labels from `labels_seg/`, and class names from an optional `data.yaml`. Missing class
names are initialized automatically. Original mask RLE, instance IDs, review state,
notes and recovery data live in `.annodesk/`; keep that directory with the project.
Do not run multiple backend processes against the same dataset yet.

The wheel includes the compiled English/light workbench; Node is only needed to
change or rebuild the frontend. No model dependencies are needed for box annotation.

## Separate API and UI machines

On the machine holding the dataset:

```sh
uv run annodesk api --host 0.0.0.0 --port 8765
```

On the machine serving the UI:

```sh
uv run annodesk ui --api-url http://gpu-host:8765 --port 8080
```

Open the UI in a browser. `gpu-host` must be reachable from that browser. Paths in
the Open project dialog always refer to the API machine. This initial deployment
has no authentication and is intended for a trusted network.

## Optional segmentation

```sh
uv sync --extra inference
uv run annodesk doctor
uv run annodesk models list
uv run annodesk models fetch sam2.1_s.pt
```

The adapter targets SAM/SAM 2, MobileSAM and SAM 3 through Ultralytics. Text prompts
require SAM 3 and separately obtained authorized weights. Weights are never downloaded
implicitly by an annotation request. Model integration tests currently use a deterministic
adapter: actual checkpoint inference, accelerator support and SAM 3 API compatibility
still need validation on the target machine. Missing dependencies/weights produce an
error while preserving annotations.

## Implemented workflow

- Persistent image tree/flat list and class palette; adjustable panels and bounded
  thumbnail loading with horizontal preview scrolling.
- Draw, resize, move, delete, lock and hide boxes; assign classes; mask-only box/point
  prompts; exact RLE overlays, pan, zoom, fit and shortcut reference.
- Autosave before navigation, optimistic revisions, late-response protection,
  review states, image notes/tags and editable class/tag colors.
- Current-image inference and persisted batch progress with cancel/resume controls.
- Backend APIs for explicit class reindexing with backups, YOLO/COCO export and
  recoverable Excluded-image cleanup. Export flushes pending browser edits first.

## Remaining work

The full specification is the target, not a claim of completion. Important pending
items include cross-process project write leases, class deletion and migration UI,
trash/restore UI, export options/report UI, central configurable shortcuts, class
favorites/virtualization, and small-screen inspector access. Import currently creates
separate instances for box and polygon rows rather than matching them automatically.
Batch resume continues unprocessed images; retrying failed images needs a new batch.
YOLO polygons cannot preserve mask holes; use COCO RLE for lossless export.

## Development and verification

```sh
uv sync
npm ci --prefix frontend
npm run dev --prefix frontend
uv run annodesk build-ui
uv run ruff format src tests
uv run ruff check src tests
uv run pytest
npm test --prefix frontend
npm run build --prefix frontend
uv build
```

The frontend development server proxies API requests to port 8765. Start
`annodesk api` separately. Commit rebuilt `src/annodesk/web_dist` with frontend
changes so an ordinary `uv sync` works without npm. Design documents are tracked;
implementation plans and previous prototypes are ignored.
