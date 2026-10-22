# Working on AnnoDesk

Read `docs/specs/annodesk.md` and its `assisted-boxes.md` extension before changing behavior. It records the product contract;
`docs/user-guide.md` is the guide shipped inside the wheel, and `README.md` describes development.
Update these documents together when behavior or commands change. Clearly distinguish implemented
features from future targets and hardware validation that has not been performed.

## Project conventions

- Use Python 3.11+ with uv; repository development uses Python 3.13. Keep `uv.lock` current.
- CLI commands use **tyro**, never argparse or Typer. Optional model imports stay lazy.
- Frontend: Vue 3, TypeScript, Pinia, Naive UI and Konva. English and Simplified Chinese UI, light theme.
- Keep changes focused. Do not add speculative frameworks, generic plugin systems or unrelated refactors.
- Never download model weights or install inference dependencies implicitly. Model IDs resolve through
  `ModelRegistry`; `source` is a directory, resolved relative to its JSON then via `HF_MODELS`.
- Device numbers are logical indices after `CUDA_VISIBLE_DEVICES`. Never rewrite that environment
  variable or treat logical indices as host GPU numbers.
- Batch workers use spawn and compute on snapshots. Only the parent coordinator writes annotations.
  Keep dispatch/results bounded, acquire the project write lease at runtime boundaries, and preserve
  revision/fingerprint validation and journaled saves.
- Internal annotation JSON/RLE is authoritative. `labels` and `labels_seg` are YOLO projections.
  Only create mask-derived boxes through the explicit geometry operation; never invent detection boxes for ordinary mask-only annotations or mark automatic masks human-approved.
- Statistics SQLite is disposable derived metadata. Log failures must not lose committed annotations.
- Log important business events explicitly; keep polling, per-box and autosave noise out of UI logs.
  Never log credentials or expanded exception locals.
- Use temporary datasets for tests/previews. Synthetic masks belong only in tests/disposable demos.

## Verification and delivery

Before every code commit:

```sh
uv run ruff format src tests
uv run ruff check src tests
uv run pytest
npm test --prefix frontend
npm run build --prefix frontend
```

Run frontend checks/build when frontend behavior or bundled assets change. Commit matching
`src/annodesk/web_dist` output so wheel users do not need Node. For release changes, run `uv build`
and smoke-test the wheel outside the checkout, including CLI help, bundled docs, model listing,
API and static resources. Do not claim CUDA/MPS compatibility based solely on synthetic tests.

Keep package versions in `pyproject.toml`, `src/annodesk/__init__.py`, frontend package/lock and
`uv.lock` aligned. Publishing requires an explicit user request; committing a version bump does
not authorize publication. Never amend a published release to add new features.

Git tracks source, tests, lockfiles and official docs. Keep plans under ignored `docs/plans/`;
previews/screenshots under ignored `docs/design-previews/`. Do not commit models, user datasets,
caches, local credentials or execution notes. Use `rg` for search and meaningful tests for risky
state transitions. When reviews are requested, evaluate findings individually, fix reproducible
issues, and reject unrelated or speculative work with a brief reason.

Detector class mappings must match exact (numeric ID, name) subsets. Never silently remap IDs,
restore deleted classes, or create unused model classes. New classes and successful image labels
commit in the same journaled transaction. Working IDs may be sparse; exports use a continuous
copy with `class-id-map.json`. Geometry-only operations must not import Torch or load models.
Models and Tasks use central windows; project review statistics remain permanently visible.
Use `frontend/src/i18n.ts` and the locale catalog for UI text, tooltips and accessibility labels.
Translate at render time so language switching stays reactive; preserve stored enums, project
class/tag names, model IDs, paths and raw diagnostics. Use whole interpolated messages for counts.
Keep bilingual wrapping and numeric alignment intact; verify both languages after UI edits.

Interactive multimask proposals follow `docs/specs/mask-candidates.md`. Keep previews transient
and bounded; applying a candidate preserves instance identity/class/box and validates revision,
image stamp and external label fingerprints. Batch/auto/single-mask inference explicitly passes
`multimask_output=False`; semantic text results are not alternative candidates. Keep at most one
in-flight candidate request per client and discard stale results after edits or navigation.
