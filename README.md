# AnnoDesk

A local-first workbench for YOLO detection boxes and instance masks.

**Using the installed package:** read the [user guide](docs/user-guide.md).
It ships inside the wheel and is available with `annodesk docs`. The guide covers
installation, model directories, annotation, review, export and headless conversion.
This README is for repository development.

## Design and implementation scope

The complete target design is in [docs/specs/annodesk.md](docs/specs/annodesk.md).
The first implementation is usable, but the full specification is not a completion
claim. Important remaining items include cross-process project write leases, class
deletion/migration UI, trash/restore UI, export options/report UI, configurable
shortcuts, class favorites/virtualization and small-screen inspector access.

The Ultralytics model integration has deterministic adapter tests; actual checkpoints,
SAM 3 dependencies and accelerator compatibility still need target-machine validation.
Weights are never downloaded implicitly, and are not included in distributions.

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
dataset. Optional inference dependencies are installed with `uv sync --extra inference`.
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

`uv run annodesk build-ui` runs npm installation, type checking and frontend bundling.
Commit matching `src/annodesk/web_dist` resources with frontend changes: an ordinary
clone plus `uv sync` can then serve the workbench without Node.

Hatchling bundles the frontend, default `models.json` and `docs/user-guide.md` into
the wheel. The user guide is also the package long description. Validate the wheel
in an isolated environment from outside the checkout, including `annodesk docs`
and `annodesk models list`, before publishing. Publication is a separate action.

Git tracks source, tests, locks and official documentation. Implementation plans,
previous prototypes, screenshots, environments, model weights and user data are ignored.
