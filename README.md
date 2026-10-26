# AnnoDesk

A local-first image annotation tool for bounding boxes and instance masks, with SAM-powered interactive segmentation and YOLO-assisted detection.

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
class deletion/migration UI, trash/restore UI, configurable
shortcuts, class favorites/virtualization.

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
Weights are never downloaded implicitly. The unmodified YOLO11n COCO checkpoint is
bundled under `assets/models/yolo11n/`, with its upstream notices and SHA256. SAM
weights remain external and resolve from the configured model root.

Version 0.2.1 removes frontend build tooling from the user CLI, orders help by task,
and keeps the shipped guide focused on installation, annotation and operation.

The current local release is **0.3.0**; see the [release notes](docs/releases/0.3.0.md) for changes, upgrade guidance and verification boundaries.

Version 0.2.2 replaces the standalone `api` command with `serve --api-only`.

The current preset selects `facebook/sam2.1-hiera-small` for segmentation and bundled
`yolo11n` for detection. `models.json` has symmetric `segmentation` / `detection`
groups with their own defaults and model lists; legacy flat files remain readable.
Model IDs for segmentation use repository IDs. Startup
warnings and bilingual model setup notices distinguish missing files from missing
inference dependencies, while manual annotation remains available.

## Release verification

The release regression suite covers journal recovery, first-read materialization,
queued inference snapshots, cross-project and cross-image edits, category/tag draft
rollback, batch/trash coordination, EXIF/TIFF coordinates and virtual-list bounds.
The 0.3.0 regression check passed 237 Python tests and 170 frontend tests, Ruff,
the frontend build and an installed-wheel CLI/API/docs/static-resource smoke test.
All eight user command help pages are checked without loading inference dependencies.
Parameter help explains omitted/None values, configuration precedence, device plans and
write policies. Read-only model listing exposes no ineffective logging options.
Synthetic protocol tests do not extend the real hardware claims above.

## License

AnnoDesk original source is MIT licensed; see [LICENSE](LICENSE). Third-party models
and dependencies retain their own licenses. In particular, the bundled YOLO11n
checkpoint is not MIT licensed; see [model notice](assets/models/yolo11n/NOTICE.md).

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
8765. Use `annodesk serve --api-only` for an API-only process. Keep a single backend writer per
dataset; CLI and API enforce this with a filesystem write lease. `uv sync` installs the shared detection and segmentation runtime, including Ultralytics. Model imports remain lazy; weights are never downloaded automatically.
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
previous prototypes, screenshots, environments, other model weights and user data are ignored. The explicitly bundled `assets/models/yolo11n/` checkpoint is the model exception.

## Deployment roles

`serve` runs the API, dataset writer and inference alongside the bundled page.
For a GPU server, run `annodesk serve --host 0.0.0.0` there and open
`http://SERVER_IP:8765` in a local browser; a separate `ui` process is unnecessary.
`serve --api-only` omits the page; `ui` hosts only static assets and the API address, for
independent web hosting or development. Browsers call that API directly.

All dataset/model paths and saves belong to the API machine. Hosting `ui` on a
laptop does not let a remote API read the laptop's dataset. Local dataset ownership
with image/prompt upload to a remote inference-only node is not implemented.
See the [deployment guide](docs/user-guide.md#8-运行位置与浏览器访问地址) for machine-by-machine commands.

## Runtime boundaries

`devices.py` resolves logical device plans using an isolated probe; `execution.py`
spawns workers with bounded per-worker inboxes and one parent writer. `batch.py`
is shared by the headless CLI and persisted `jobs.py` API jobs. `events.py` owns
Loguru session sinks, the bounded important-event ring and SSE; `statistics.py`
maintains a disposable SQLite review index after successful annotation commits.
Exports remain directory exports (no archive or browser upload/download of datasets).
Tasks opens automatically when a task starts; closing it leaves a compact toolbar
progress indicator without occupying canvas space. Logs is independent of an open project.

Package and frontend metadata are aligned at 0.3.0. Releases use annotated Git tags;
commit messages describe changes without version numbers. Publishing is an explicit
release step after checks and an outside-checkout wheel smoke test.

Detection adapters return candidates without project access; `operations.py` validates
strict numeric class mappings and commits new classes with annotations in one journaled
transaction. Working class IDs may be sparse; exports contain continuous IDs and
`class-id-map.json`. `boxes-from-masks` uses CPU geometry without importing Torch or loading models.

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

## Interactive annotation and export

Point and box prompts update the selected mask automatically after a short debounce. Prompt previews are read-only until the client validates its current editing context. Creation tools and selection targets separate annotation results from SAM prompts. Detection boxes use solid class colors; SAM box prompts use amber dashes. Direct geometry buttons select overlapping targets. Lossless mask pixels, boxes and individual prompts can be selected independently; deletion preserves the other geometry. `N` starts the next object; clearing all prompts preserves the existing mask without running inference. `Shift+X` or `Shift+Delete` removes an entire object with its prompts, with undo support. `Segment current` fills missing masks and reports when there is no work. The canvas keeps a single 48px toolbar; the right inspector has fixed geometry columns, a single expanded object row for class/inference/geometry actions, and permanent image properties below. Both regions scroll independently with adjustable proportions. Missing geometry keeps a disabled slot; More and right-click share one context menu. Selection never changes canvas size; Clear all prompts removes unlocked prompts across the current image with one undo step. Resize handles are kept out of canvas selection routing.

Mask-derived boxes support per-side pixel/ratio padding and the smaller of both, clipped to image bounds. UI uses percentages of mask bounds; CLI/API ratios use fractions (`--box-padding-ratio 0.1` = 10% per side). Defaults preserve tight bounds. Settings are available for current-image and batch geometry operations; no model is loaded. Undo/redo have a separate History tool group, and Edit SAM prompts directly enables prompt selection.

Above object search, the inspector provides a contextual, undoable Clear image annotations confirmation (locked objects preserved unless explicitly included). Text prompts float over the canvas without reflow, tool cursors indicate interaction mode, and V restores result selection. Clicking the same object name toggles its inline details while keeping selection.

Annotation statistics now include saved box/mask totals and a class breakdown window (table or paginated horizontal bars). Geometry counts exclude discarded images by default; review totals always cover the project. The rebuildable index reads authoritative JSON or unmaterialized YOLO labels without loading pixels. Text prompts use a wider multiline overlay; drawing cursors keep the arrow hotspot and add distinct tool badges. Auto-segment defaults on for pending, non-excluded images with available models and eligible missing masks.

The workbench Batch dialog can start directly: Start saves current edits and runs scope/model compatibility checks before submitting a job. Preview scope is optional; an empty scope is reported without creating a job. Task polling preserves completed jobs and statistics during same-session metadata refreshes.

Export opens a statistics/confirmation dialog with task, YOLO/COCO, pending-label and backend destination options. Read-only `/export/preview` returns eligibility, review/skip counts and a source signature; jobs validate that signature before writing. Empty/invalid exports are rejected. Completed copies have a file checksum manifest and project history for intact, unchanged export reuse; existing output directories are never overwritten. Cancellation also applies before returning a reused export and preserves the existing copy. Image-wide annotation actions sit above the object search, and Auto-detect remains off by default.

Review summaries display Approved/total with four mutually exclusive states (Not reviewed, Approved, Needs review, Excluded); no combined Reviewed group. Export skip details open automatically when images are omitted and list up to 100 paths with reasons, including unannotated images that were not explicitly confirmed empty.


Classes, Tags, Models, Tasks, Logs, Statistics and Shortcuts use temporary centered
modal windows. Close them to continue annotation; closing Tasks or Logs does not
stop processing or log files. Ordinary errors use fixed, non-blocking notifications
without changing the workspace layout. Approval of an unannotated image requires
explicit confirmation that the current task contains no objects. This confirmation
sits immediately below review controls and does not automatically approve the image.

Export summaries group images by four review states and show a nested
“No valid annotations” subset for each state, excluding confirmed empty images.
Skipped-file details have their own bounded scroll area. The API includes
`skipped_by_state` and `skipped_no_valid_annotations`; unknown review states are
reported separately. Full user workflows and shortcuts are in the shipped guide.
