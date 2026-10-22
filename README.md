# AnnoDesk

A local-first workbench for YOLO detection boxes and instance masks.

**Using the installed package:** read the [user guide](docs/user-guide.md).
It ships inside the wheel and is available with `annodesk docs`. The guide covers
installation, model directories, annotation, review, export and headless conversion.
This README is for repository development.

## Design and implementation scope

The complete target design is in [docs/specs/annodesk.md](docs/specs/annodesk.md).
Version 0.2.0 adds offline YOLO detection preannotation, strict detector/project class
validation, lazy transactional class creation, mask-to-box geometry, review-aware batch
scopes, and central Models/Tasks windows. See the [assisted annotation specification](docs/specs/assisted-boxes.md).
Spawned multi-device processing, a project write lease, Loguru/SSE logs and persistent
review statistics remain shared infrastructure. The full specification is not a completion claim. Remaining items include
class deletion/migration UI, trash/restore UI, export options/report UI, configurable
shortcuts, class favorites/virtualization and small-screen inspector access.

The interface supports English / Simplified Chinese switching with browser-local persistence,
localized controls and tooltips, and bilingual layout adjustments. UI messages live in
`frontend/src/i18n.ts` and `frontend/src/locales/zh-CN.json`; project data and raw logs retain
their original values. Translation coverage and placeholder tests run with the frontend suite.

Interactive segmentation includes on-demand mask candidates; see the [candidate spec](docs/specs/mask-candidates.md).
Proposals are stateless, read-only previews; an explicit selection is applied through the
existing journaled save with revision and image fingerprint checks. Batch and automatic
segmentation remain single-mask operations. Candidate quality uses the predictor's score,
not detection confidence; semantic text segmentation remains a separate multi-object path.

Read [AGENTS.md](AGENTS.md) for contributor conventions. The execution layer is
covered by actual spawn tests with synthetic adapters, including the single-writer
commit path. Version 0.2.0 was also checked with real SAM 2.1 Tiny and YOLO11n weights
on 16 COCO images, CPU and Apple MPS (including two workers); see the
[real-model validation report](docs/validation/real-models-2026-10-22.md).
CUDA, other model families and other dependency versions remain unverified.
Weights are never downloaded implicitly, and are not included in distributions.

Version 0.2.1 removes frontend build tooling from the user CLI, orders help by task,
and keeps the shipped guide focused on installation, annotation and operation.

## Release verification

The release regression suite covers journal recovery, first-read materialization,
queued inference snapshots, cross-project and cross-image edits, category/tag draft
rollback, batch/trash coordination, EXIF/TIFF coordinates and virtual-list bounds.
The 2026-10-23 patch release check passed 183 Python tests and 84 frontend tests, Ruff,
the frontend build and an installed-wheel CLI/API/docs/static-resource smoke test.
All nine user command help pages are checked without loading inference dependencies.
Synthetic protocol tests do not extend the real hardware claims above.

## Development setup

Python 3.11+ is supported; the repository uses Python 3.13. Install uv and Node/npm
for development, then:

```sh
uv sync
uv run annodesk serve --project /absolute/path/to/dataset
npm ci --prefix frontend
npm run dev --prefix frontend
```

The frontend development server proxies `/api` and runtime UI configuration to port
8765. Use `annodesk api` for an API-only process. Keep a single backend writer per
dataset; CLI and API enforce this with a filesystem write lease. Optional inference dependencies are installed with `uv sync --extra inference`.
User paths, local model preparation and deployment commands are documented in the
user guide rather than duplicated here.

## Checks and builds

```sh
uv run ruff format src tests
uv run ruff check src tests
uv run pytest
npm test --prefix frontend
npm run build --prefix frontend
uv build
```

Frontend development uses `npm ci --prefix frontend` followed by
`npm run build --prefix frontend` for type checking and bundling. The installed
`annodesk` CLI exposes user commands only; the former `build-ui` command was removed.
Commit matching `src/annodesk/web_dist` resources with frontend changes: an ordinary
clone plus `uv sync` can then serve the workbench without Node.

Hatchling bundles the frontend, default `models.json` and `docs/user-guide.md` into
the wheel. The user guide is also the package long description. Validate the wheel
in an isolated environment from outside the checkout, including `annodesk docs`
and `annodesk models list`, before publishing. Publication is a separate action.

Git tracks source, tests, locks and official documentation. Implementation plans,
previous prototypes, screenshots, environments, model weights and user data are ignored.

## Runtime boundaries

`devices.py` resolves logical device plans using an isolated probe; `execution.py`
spawns workers with bounded per-worker inboxes and one parent writer. `batch.py`
is shared by the headless CLI and persisted `jobs.py` API jobs. `events.py` owns
Loguru session sinks, the bounded important-event ring and SSE; `statistics.py`
maintains a disposable SQLite review index after successful annotation commits.
Exports remain directory exports (no archive or browser upload/download of datasets).
Tasks opens automatically when a task starts; closing it leaves a compact toolbar
progress indicator without occupying canvas space. Logs is independent of an open project.

Package and frontend metadata are aligned at 0.2.1. Releases use annotated Git tags;
commit messages describe changes without version numbers. Publishing is an explicit
release step after checks and an outside-checkout wheel smoke test.

Detection adapters return candidates without project access; `operations.py` validates
strict numeric class mappings and commits new classes with annotations in one journaled
transaction. Working class IDs may be sparse; exports contain continuous IDs and
`class-id-map.json`. `boxes-from-masks` uses CPU geometry without Torch or model loading.

Project requests and queued inference are bound to a runtime session and annotation
snapshot. Stale requests cannot overwrite newer edits or another project. Interrupted
saves retain their recovery journal and block further writes until backend restart.

Display, inference and export use the same decoded image coordinates, including EXIF
and TIFF inputs; exports normalize image copies when necessary. Internal JSON/RLE
remains authoritative for YOLO projections. See the [product spec](docs/specs/annodesk.md)
for consistency guarantees and the [user guide](docs/user-guide.md) for recovery steps.

Custom API clients should send the runtime `session` from `/project` as
`X-AnnoDesk-Project` (or `project_session` for media URLs). Requests without this context
remain compatible with protocol 1 and do not receive the cross-project check; the session
is not authentication. `/images/{id}/file` returns a metadata-free PNG preview.
