# AnnoDesk User Guide

AnnoDesk annotates detection boxes and instance masks in images. You can import existing YOLO detection labels, generate masks from boxes, and review the results manually. The browser interface supports English and Simplified Chinese with a light theme. Images, models, and annotations stay on the computer running the backend.

Version: 0.3.1.

## 1. Installation

Python 3.11 or newer is required. Use a separate Python environment:

```sh
python -m venv .venv
```

Activate it on macOS / Linux:

```sh
source .venv/bin/activate
```

Or in Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Install a local release package. For offline installation, prepare its dependencies beforehand:

```sh
python -m pip install ./annodesk-0.3.1-py3-none-any.whl
```

Once this version is available on PyPI, you can also install it by name:

```sh
python -m pip install "annodesk==0.3.1"
```

A standard installation includes the shared detection and segmentation dependencies, Ultralytics / PyTorch. No extra installation option is needed. Check the environment with:

```sh
annodesk doctor
```

`doctor` checks whether torch / ultralytics are installed; it does not validate weights, GPU drivers, or inference results. Configure PyTorch GPU support for your machine separately. SAM 3 text inference also requires its local tokenizer and runtime dependencies.

Dependency installation may access a Python package index. Inference never downloads model weights or installs missing dependencies automatically.

Before upgrading, stop the service and back up the entire project, especially `.annodesk/`. Then run:

```sh
python -m pip install --upgrade ./annodesk-0.3.1-py3-none-any.whl
```

For upgrades from PyPI, use the package name and appropriate version. Restart the service and refresh the page after upgrading. Existing annotations retain their review states.

## 2. Starting the workbench and opening a dataset

```sh
annodesk serve --project /data/my-dataset --open
```

The default address is `http://127.0.0.1:8765`. `--open` requests a browser window; you can also open that address yourself. Keep the terminal running and press Ctrl+C to stop the service.

You can start without a project and enter a path through **Open project…**:

```sh
annodesk serve
```

An empty workbench before opening a project is normal. Paths always refer to the backend computer, not the browser computer. If the port is occupied, choose another:

```sh
annodesk serve --port 8766
```

When several browser tabs share one backend, switching projects in one tab makes older tabs report that the project has changed. Check the backend's target directory and reopen the project. Switching may be refused while saving or inference is in progress; retry after it finishes. Editing is temporarily disabled while opening projects or navigating between images.

Only one AnnoDesk service or batch command may write to a dataset at a time. Stop the service using that project before running a separate `segment`, `detect`, or `boxes-from-masks` command. The operating system releases the lock after an abnormal exit; do not delete lock files to bypass it.

## 3. Preparing a dataset

Recommended working layout:

```text
my-dataset/
├── images/
│   ├── train/camera_a/001.jpg
│   └── val/camera_b/002.jpg
├── labels/                 # YOLO detection labels; optional
├── labels_seg/             # YOLO segmentation labels; optional
└── data.yaml               # Class names; optional
```

`train`, `val`, and `test` are not required to open a project. Nested directories are supported. Label paths mirror the image's relative path under `images/`:

```text
images/train/camera_a/001.jpg
labels/train/camera_a/001.txt
labels_seg/train/camera_a/001.txt
```

Images need not have labels yet. AnnoDesk creates `data.yaml` if it is missing. Existing labels without class names receive placeholder names such as `class_0`. You can also open an image directory directly; labels and `.annodesk/` will be written inside it, so a dedicated working directory is recommended.

Files such as `001.jpg` and `001.png` in the same directory would share one label filename and must be renamed first. Imported detection and segmentation labels currently create separate instances; they are not automatically matched or merged.

YOLO box values must be within `[0,1]`, and the converted box must have positive area and stay inside the image. Invalid imports report the label file and line number without creating an internal annotation. Only tiny floating-point rounding errors at the boundary are tolerated. Correct the source TXT file and reopen the image. Detection export also rejects out-of-bounds boxes in older internal records.

Display and inference use the same first-frame RGB raster. JPEG annotations follow the stored raster without an additional EXIF rotation: a `120×80` image with orientation 6 still uses `120×80` coordinates. TIFF uses its decoded dimensions. The main canvas receives a full-resolution PNG preview without orientation metadata, so TIFF can also be displayed in the browser. Multipage TIFF and animated images use only their first frame; display and inference use RGB/8-bit pixels. Original images remain unchanged. Review existing labels manually if they used a different orientation; upgrades do not transform those coordinates.

For training exports, TIFF, images with rotated/mirrored EXIF orientation, and animated images become PNG copies. Image lists and COCO paths are updated; box/mask coordinates stay the same, preventing training tools from rotating them again. Ordinary static images are copied as they are.

### Working files and backups

- `labels/`: explicit detection boxes. Mask-only annotations do not create boxes automatically.
- `labels_seg/`: YOLO polygon projections of segmentation results.
- `.annodesk/`: instances, lossless mask RLE, review states, prompts, task progress, and recovery information.
- `data.yaml`: class names and dataset configuration.

Back up the whole working directory, including `.annodesk/`. YOLO polygons cannot fully represent holes and cannot replace the internal lossless masks. Avoid editing labels with other tools while the project is open. If external changes are detected, saving reports a conflict; back up and compare the files before proceeding.

## 4. Configuring local models

The preset configuration is available without `--models-config`:

- Segmentation defaults to `facebook/sam2.1-hiera-small` (SAM 2.1 Small). Other SAM 2.1 sizes, MobileSAM, and SAM 3 also have repository-ID presets.
- Detection defaults to `yolo11n` with 80 COCO classes. Its weights are bundled, and a standard installation includes inference dependencies.
- SAM weights are not bundled or downloaded automatically. Place compatible weights in `$HF_MODELS/facebook/sam2.1-hiera-small/`, for example `sam2.1_hiera_small.pt`. A directory containing only `model.safetensors` is not supported by the current inference adapter.

```sh
export HF_MODELS=/srv/models
annodesk models list
annodesk serve --project /data/my-dataset --open
```

In Windows PowerShell, use `$env:HF_MODELS = "D:\models"`. `HF_MODELS` is the root containing directories such as `facebook/`, not a `.pt` file or an individual model directory.

If default weights or inference dependencies are missing, startup prints a warning and the page shows a setup notice for the current Detection / Segmentation task. Open **Models** to inspect settings. Manual annotation remains available. After preparing weights, click **Reload configuration**. Restart the backend after installing dependencies. Available weights alone do not confirm that dependencies, devices, and class compatibility are ready.

Reloading configuration clears the previous class compatibility result. If the selected model was removed, the task's valid default is selected. Models that remain available retain their unapplied parameter drafts.

Create a custom `models.json` when needed:

```json
{
  "segmentation": {
    "default_model": "facebook/sam2.1-hiera-small",
    "models": [
      {
        "id": "facebook/sam2.1-hiera-small",
        "name": "SAM 2.1 Small",
        "backend": "sam2",
        "source": "facebook/sam2.1-hiera-small"
      },
      {
        "id": "dhkim2810/MobileSAM",
        "name": "MobileSAM",
        "backend": "mobile_sam",
        "source": "/srv/models/MobileSAM"
      }
    ]
  },
  "detection": {
    "default_model": "detector",
    "models": [
      {
        "id": "detector",
        "name": "My detector",
        "backend": "ultralytics",
        "source": "/srv/models/my-detector"
      }
    ]
  }
}
```

`segmentation` and `detection` each contain `default_model` and `models`. A default ID must belong to its group; if omitted, the first model in that group is selected. You can omit a group when using only one task.

- `id`: a unique identifier referenced by `--model` and defaults. Preset segmentation IDs use full repository IDs to distinguish model sizes; custom configurations may use other unique names.
- `name`: display name in the workbench.
- `backend`: `sam`, `sam2`, `mobile_sam`, or `sam3`; detection uses `ultralytics`.
- `source`: the final model directory. Do not specify a `.pt` / `.safetensors` file or a `checkpoint` field.

### Resolving model directories

After expanding `~` and environment variables:

1. Absolute paths are checked directly. A missing absolute directory is an error; no prefix is added.
2. Relative paths are resolved against the JSON file's directory and used if that directory exists.
3. If it does not exist, AnnoDesk checks `$HF_MODELS/<source>`. There is no fallback when `HF_MODELS` is unset.

Repository IDs follow the same rules as relative directories; they do not contact Hugging Face. With JSON at `/work/models.json` and source `facebook/sam2.1-hiera-small`, AnnoDesk checks `/work/facebook/sam2.1-hiera-small`, then `$HF_MODELS/facebook/sam2.1-hiera-small`.

Set the root on macOS / Linux:

```sh
export HF_MODELS=/srv/models
```

Or Windows PowerShell:

```powershell
$env:HF_MODELS = "D:\models"
```

AnnoDesk searches the selected directory's top level, preferring known `.pt` filenames for the backend. If none match, it accepts a single `.pt` file. Multiple candidates are an error; keep each model in its own directory.

**Prepare Ultralytics-compatible `.pt` weights.** A Hugging Face directory does not guarantee a compatible format; safetensors-only repositories are unsupported. Once a directory is found, missing compatible weights do not cause another directory to be selected or a download to start. Official Meta SAM2 Hiera `.pt` files do not need renaming.

SAM 2.1 Tiny and YOLO11n have been tested on Apple M2 Max with CPU/MPS inference and two workers. Small, other models, CUDA, and other dependency versions still require validation on the target system.

### Choosing a configuration and switching models

```sh
annodesk models list --models-config ./models.json
annodesk serve --project /data/my-dataset --models-config ./models.json
```

Configuration precedence is `--models-config`, then `ANNODESK_MODELS_CONFIG`, then `models.json` in the current directory, then the default preset (repository configuration when running from source, or bundled configuration when installed).

Pass `--models-config` explicitly for custom setups. It replaces the preset rather than merging with it. The canvas toolbar opens the central **Model settings** window with Detection / Segmentation sections:

- **Available** means the directory and weights are available; **Loaded** means the model has been loaded.
- **Reload** rereads configuration; **Check classes** validates detector class compatibility; **Load** loads onto the selected device.
- **Apply** saves project/model parameters. **Cancel** discards unapplied parameters but does not undo a completed Load.

Hover hints omit server paths. Expand Diagnostics or use the CLI for detailed errors. If a SAM model fails to load, retry or switch back and reload the previous model without restarting the backend.

### Detector classes and project compatibility

Older flat configurations with top-level `default_model`, `default_detection_model`, and `models` remain readable. Do not mix flat and grouped formats. Model IDs must be globally unique. Unknown fields and task/backend mismatches are rejected.

Standard Ultralytics detector `.pt` files usually contain class names; see the [official prediction documentation](https://docs.ultralytics.com/modes/predict/). If names are missing or only placeholders such as `class_0`, add `"classes_file": "detector-classes.yaml"` to the model entry:

```yaml
names:
  0: cat
  1: dog
```

JSON `names` lists or dictionaries are also supported. The class file is resolved relative to `models.json`, or can use an absolute path; it does not use `HF_MODELS`. Model IDs must be contiguous `0..nc-1`. If both weights and the file contain reliable names, they must agree exactly; a file cannot override real model classes. Arbitrary third-party state_dict-only files are not guaranteed to load.

The model and project `(ID, name)` sets must be identical, or one must be a subset of the other. Conflicts are errors; IDs are not silently remapped and names are case-sensitive. Provide the correct `data.yaml` when importing YOLO data. Placeholder names are not treated as equivalent to real names.

**Allow new classes from this model** defaults off. Detections outside project classes are discarded. When enabled, only classes that actually occur in accepted detections are added, together with a successfully saved image, retaining the original model IDs. An empty project is allowed, but with this option off and no acceptable classes, detection fails. This setting is stored per project/model. Wait for detection batches to finish before adding, renaming, or reindexing project classes; colors may still be changed.

Working class IDs may have gaps and are not filled on reopening. Such a `data.yaml` is not guaranteed to train directly. Use Export to create a training copy with contiguous IDs and `class-id-map.json`, leaving working IDs unchanged.

## 5. Annotating in the workbench

### Interface language

Use the top-right language selector to switch immediately between **English / Simplified Chinese**. English is the initial default. The selection is stored for the current browser site and persists across reloads. When local storage is disabled, the workbench still starts and supports language switching and resizing; settings apply only to that page and may be lost on reload. Each browser or device can use its own language without a server restart.

Controls, tooltips, review labels, and shortcut descriptions are translated. Shortcut mappings are unchanged, and single-key shortcuts are suppressed during IME composition. Class/tag names, model IDs, paths, and raw diagnostics/logs retain their original values. Interface language does not change a model's supported text prompt languages; use English prompts where required by the current model.

### Browsing images and assigning classes

The image list supports **Tree / Flat**, search, and directory expansion. Search, directory expansion, list-mode, or project changes reset scrolling to the top. The bottom filmstrip scrolls horizontally and loads thumbnails on demand; search or project changes reset its position. Drag panel dividers to change proportions.

The lower-left **Class palette** assigns classes:

- With no instance selected, click a class to set the default for new annotations.
- **Default class** clears instance selection and returns to choosing the default.
- With a box or mask selected, clicking a class changes that instance.
- Press **C** to search classes; use ↑ / ↓, Enter, and Esc to choose, confirm, or cancel. Double-click an instance in selection mode to open the picker.

**Classes** at the top manages class names and colors. Names must be nonempty and unique within the class or tag dictionary. The edited row is disabled while saving; a failed save restores its original value and shows an error. IDs normally stay stable. **Reindex IDs…** rewrites the project's class mapping and label files; back up the project first.

### Drawing boxes and generating masks

1. Choose a class in the Class palette.
2. Use **Detection box** to draw a box. Switch to **Select** to move or resize it; coordinates can also be edited on the right. Navigating or changing projects/tools during an unfinished gesture cancels it rather than applying it to another image.
3. Select an explicit detection box and press Enter or click **Refine mask** in its instance details to generate a mask. Segmentation box prompts and points update masks automatically.
4. **Segment current** fills missing masks for unlocked detection boxes or point/box prompt drafts on the current image.

Moving, resizing, or editing a detection box keeps its associated mask and marks Segmentation **Needs review**. A box-only instance does not affect segmentation review. Locked coordinates cannot be edited. Coordinate edits and ordinary interactive segmentation support undo.

Creation tools have separate **Labels** and **SAM** groups. **Detection box** creates a saved annotation, drawn as a solid line in the class color. Positive/negative points, **SAM box prompt**, and text guide segmentation. Prompt boxes use amber dashes and are not exported as detection boxes.

**Select** targets annotation results by default; prompt boxes and points cannot intercept box/mask selection. Choose **Edit SAM prompts** to select prompts. Geometry buttons in the right-hand instance list/details select a box, mask, or prompt explicitly even when they overlap completely. Only the selected target shows resize handles.

For mask-only annotations, use **SAM box prompt** or positive/negative points. Prompt boxes and detection boxes are stored separately. Positive points include regions; negative points exclude them. The text tool requires a text-capable SAM 3 model and a default class.

**Auto-segment** defaults on. When entering a non-excluded image with segmentation Not reviewed and eligible boxes, it fills missing masks for visible, unlocked boxes. Existing masks are preserved. A locally available segmentation model and dependencies are required; otherwise no automatic request is dispatched. In Detection, **Detect current** and **Auto-detect** are available. Auto-detect defaults off and only processes non-excluded, Not reviewed images with no instances.

**Batch…** offers Detect boxes, Segment existing boxes, or Boxes from masks for all project images or the current search results. Only Not reviewed is selected by default; Needs review / Approved can be explicitly included. Excluded images are always skipped. Detection and mask-to-box operations use Detection review; SAM uses Segmentation review.

Click **Start** directly to save current edits, check scope and detector class compatibility, and launch if any images are eligible. With none eligible, scope statistics are shown without creating an empty task. **Preview scope** is an optional read-only check showing skipped categories and invalid inputs. Starting revalidates and freezes the scope/configuration. Device and worker rules are in section 6.

Tasks automatically open a central, resizable **Tasks** window, about 900px wide. Closing it restores annotation while work continues, with a compact toolbar indicator such as `Tasks ◌ 60/75` and a thin progress bar. Details include start time, elapsed time, succeeded/failed/skipped/remaining counts, new boxes/classes, frozen parameters, each worker's current image, and errors. Scanning, model loading, and final export stages show indeterminate activity rather than invented percentages. Project statistics remain visible.

Cancellation stops new dispatch; in-flight images are saved before it takes effect. Resume retains the original scope and model/device/parameter snapshot and processes only remaining work. Changed weights or class mappings require a new task. Queued images that no longer meet the review criteria are rejected and counted as failures, preserving manual review. Retry failed images in a new batch after fixing the cause. If another program removes an image during a batch, its original path is recorded as a failure and unrelated images continue. Completion does not steal focus, and disconnecting the browser does not cancel tasks. Logs use their own central window.

Progress uses `finished = succeeded + failed`, with skipped images excluded from the denominator. Success is counted only after saving. For example, `60/75 finished · 58 succeeded · 2 failed · 25 skipped` leaves 15 images unprocessed. Startup failure is reported once for the task rather than as a failure for every image.

Instances can be deleted, locked, or hidden on the right. Unlock before changing a class. Hiding affects display, not export. Use the wheel to zoom around the cursor. **Pan**, zoom, and **Fit image** are grouped at the canvas's top right. Toggle Pan or hold Space temporarily; dragging from inside a box pans the canvas while selection, box dragging, and resizing are suspended.

### Refining masks and choosing candidates

Adding/removing a point or completing/adjusting a **SAM box prompt** updates the selected instance's single mask after roughly 350ms of debounce. Repeatedly clicking Segment current is unnecessary. Instance details show waiting, inference, completion, or failure. Continuous edits retain only the latest prompts. Navigation, tool/model changes, and other edits invalidate older responses. Failed inference preserves the existing mask; use **Refine mask** to retry.

Instance details include class changes, refinement, candidates, mask-to-box conversion, and deletion of the current target. On narrow windows, **Image details** opens the inspector; closing it does not interrupt inference. Details expand within the instance row without changing canvas dimensions. The instance list and image properties scroll independently. Box and prompt corners resize their geometry; borders allow dragging without confusing resize handles with mask selection.

The image-wide **Clear prompts** button above object search removes points and prompt boxes from all unlocked instances, including hidden ones. It preserves masks, detection boxes, and locked instances, and does not rerun inference. Prompt-only drafts with no remaining geometry are removed. Undo restores the entire operation.

Once a mask is satisfactory, click **New object** or press **N**. Existing labels remain, and new clicks will no longer refine the previous object. Segmentation selects positive points, or retains the prompt-box tool if already active; Detection selects box drawing. The new instance is created on the first point or drawing gesture. Esc can also clear selection before starting another object.

Within one instance, **Clear prompts** removes its points and prompt box without changing its mask or detection box. **Delete object**, **Shift+X**, or **Shift+Delete** removes the complete instance, including all geometry and prompts, with undo. **Delete mask only** retains prompts for further refinement.

In the SAM prompts selection scope, click a point or amber prompt box and press **X or Delete** to delete just that prompt. **Delete prompt** and **Clear prompts** are also available in details. Removing a single prompt recalculates the mask when prompts remain; clearing all prompts does not. In result selection, clicking the detection-box border then deleting removes only the box; clicking inside the mask then deleting removes only the mask. Selecting the whole instance in the list permits whole-instance deletion. Masks are selected through their nontransparent pixels; holes do not intercept clicks. Selected masks have blue edges with white outlines, including holes and disconnected regions.

**Segment current** fills missing masks and preserves existing results. If none need filling, it reports that there is no work. It can process point/box prompt drafts, while batch/CLI segmentation uses existing detection boxes only. A prompt box never creates a detection annotation.

Refine mask, Auto-segment, Segment current, and batch/CLI segmentation use single-mask inference. For ambiguous boundaries or object granularity, select a visible, unlocked instance with points or a box prompt and choose **Generate candidates**. SAM / SAM2 / MobileSAM / SAM3 visual prompts are supported by the adapters; text-based multi-object segmentation is separate. Actual model/dependency combinations require validation on the target environment.

A temporary candidate strip appears above the image filmstrip with up to three alternatives, ordered by predicted mask quality. Missing scores display only the candidate number. Scores estimate mask quality; they are not measured accuracy or probabilities. Selecting a candidate previews one alternative for that instance at a time.

- **Apply** or Enter saves the chosen mask, preserving instance ID, class, explicit box, and prompts. Only Segmentation returns to Not reviewed; no detection box is created. Applying supports undo; mask-only undo does not invalidate Detection review.
- **Cancel** or Esc discards the preview and restores the original mask. Previews do not enter autosave or review statistics.
- With the candidate strip focused, ← / → select candidates. Elsewhere they continue navigating images. Inputs and other dialogs take precedence.
- Further prompt edits invalidate and regenerate candidates after saving/debounce. Repeated edits coalesce instead of queuing indefinitely. Class/lock/other annotation edits, model changes, or selecting another instance cancel the old preview.
- Navigation discards unapplied candidates and notifies you while saving normal annotations. Generation failures preserve the old mask. If image content, revision, or external labels changed before applying, the result is rejected; inspect the latest state and regenerate.

Candidates are alternative masks for one object, not separate objects. SAM 3 text results use their own multi-instance flow.

### Generating detection boxes

Detection settings include Confidence, NMS IoU, Image size, Max detections, model class filters, and devices. **Empty images only** skips an image with any existing instance. **Append with duplicate checks** explicitly permits additions, skipping same-class boxes with IoU ≥ 0.7 and preserving manual boxes/masks. Confidence is stored internally without adding a YOLO TXT column. New boxes set Detection to Not reviewed; no detections do not automatically confirm an empty image.

**Create box from mask** adds a box to the same instance. **Recalculate box** explicitly replaces an existing box. Image-wide and batch **Boxes from masks** fill missing boxes and skip locked instances by default. This uses CPU geometry without loading a model, preserves mask/class/instance ID, and resets only Detection review. Later mask edits do not update the box automatically; recalculate explicitly. Ordinary mask-only SAM annotation does not save a box.

### Saving, review, and tags

Edits save automatically, including before navigation. The footer shows save status. On failure, inspect the error and use **Retry save**; confirm success before closing the page.

If an unfinished transaction is reported, restart the backend to recover it. Saving, export, and trash operations remain blocked until recovery. Empty inference results preserve the existing annotation. If an image or its labels changed while processing, check the current state and retry; stale results cannot overwrite new edits.

| State | Meaning |
| --- | --- |
| Not reviewed | Not yet manually reviewed |
| Approved | Reviewed and accepted for the current task |
| Needs review | Requires another check for the current task |
| Excluded | Excluded from processing/export without deleting the image |

Detection and Segmentation keep their first three states separately. Excluded applies to the whole image and can be toggled off. Editing labels may return the affected task to Not reviewed.

The permanent statistics bar covers the whole project for the active task, independent of image-list search. **Approved N/total** is followed by four mutually exclusive counts that sum to the total. Excluded takes precedence; removing it restores the previous task state. Automatic masks do not count as approved. Statistics reflect successful saves, show Loading statistics while indexing, and No images for an empty project.

Images accept comma-separated custom tags and notes. **Tags** displays the four built-in review states as read-only, followed by editable custom tag names/colors. Renaming a custom tag does not migrate tag strings already stored on images; check these manually.

### Export

**Export** opens a summary before writing: total images, four review states, eligible images, and skip reasons. Choose Detection / Segmentation and YOLO / COCO. Only Approved images are included by default; explicitly include Not reviewed annotations when needed. Needs review and Excluded are always skipped. Click **Confirm export** after checking the summary. Option/path changes recalculate it; zero eligible images or invalid inputs disable confirmation. Export covers the selected task across the project, not just the current image.

Unreviewed images, Needs review, Excluded, and images with unassigned classes are skipped by default. To export an empty image as a negative sample under the default policy, check **Confirm no objects for this task** and approve it.

Export opens Tasks, whose compact toolbar indicator remains when closed. Progress counts inspected images; final report writing shows an activity indicator. Output defaults to `.annodesk/exports/<id>/` on the backend. You may choose a new backend directory before confirmation, using an absolute path or one relative to the project root. Choose a location outside the working dataset, except for the default private export directory, to prevent rescanning the exported copy. Existing directories are not overwritten.

Tasks shows the path and actual exported/skipped counts. Export produces a directory, not an archive or browser download. It includes copied images, standard `labels/`, class configuration, and reports. Segmentation working labels from `labels_seg/` become standard `labels/` in the copy. Exported class IDs are contiguous, and `class-id-map.json` maps working numeric IDs to exported IDs. The working project is unchanged.

Cancellation remains available during final report writing and removes only the current incomplete output, preserving earlier exports. YOLO polygons cannot fully preserve holes; keep the original project and lossless masks in `.annodesk/`. Images without valid task labels or explicit empty confirmation are not exported as negative samples. The UI currently has no trash-management view.

## 6. Batch processing without the workbench

```sh
annodesk segment --project /data/my-dataset --models-config ./models.json --model facebook/sam2.1-hiera-small
```

Omitting `--model` uses `segmentation.default_model`; detection uses its group's default. This command starts neither an HTTP server nor a browser.

- Detection boxes/classes are preserved. Segmentation projections go to `labels_seg/`, and lossless RLE is stored internally.
- By default, only Segmentation Not reviewed is processed. Existing masks, locked instances, and Excluded images are skipped.
- `--review-states pending uncertain ok` explicitly widens the review scope without permitting replacement of manual results.
- Each image saves independently. Rerunning after interruption skips completed masks.
- The console shows stages and totals. The execution plan and per-image results are in `.annodesk/segment-report.json`.
- The first Ctrl+C stops dispatch and saves in-flight results; the second forces termination. Unsaved results are not counted as successful.
- Exit codes: 0 for completion without image failures; 1 for image failures; 2 for configuration/device/startup failures; 130 for cancellation/interruption.

Review generated results in the workbench. Commands do not automatically mark them Approved.

### Detection and mask-to-box conversion

```sh
annodesk detect --project /data/my-dataset --models-config ./models.json \
  --model detector --allow-new-classes --confidence 0.3 \
  --device-type cuda --devices 0,1 --num-workers 3
annodesk boxes-from-masks --project /data/my-dataset
```

Detection defaults to Detection Not reviewed images with no instances. `--write-policy append` permits additions, and `--model-classes 0 1` filters model classes. Confidence, IoU, image size, and maximum detections are configurable. Results are recorded in `.annodesk/detect-report.json`. `--model` always refers to a configured ID, not a weight filename.

Mask-to-box conversion needs no model and does not load Torch. `--recalculate-boxes` permits replacing unlocked boxes. Its report is `.annodesk/boxes-from-masks-report.json`. Both commands support `--review-states pending uncertain ok`, defaulting to pending, and share segment's exit codes, project lock, logging, and cancellation behavior. See each command's `--help`.

`annodesk boxes-from-masks` does not read model configuration. It works even if `ANNODESK_MODELS_CONFIG` points to a missing or malformed file.

### Devices and workers

```sh
CUDA_VISIBLE_DEVICES=2,5 annodesk segment --project /data/my-dataset \
  --models-config ./models.json --model facebook/sam2.1-hiera-small \
  --device-type cuda --devices 0,1 --num-workers 3
```

`--device-type auto|cuda|cpu|mps` defaults to auto, choosing CUDA, then MPS, then CPU. Explicitly selecting unavailable hardware fails; inference failures do not silently fall back to CPU. `--devices auto` selects all visible CUDA devices. `0,1` are logical indices after `CUDA_VISIBLE_DEVICES`; the example maps them to host GPUs 2 and 5. CPU/MPS accept only auto.

`--num-workers auto` uses one worker per selected CUDA device, or one for CPU/MPS. You can supply a positive integer. Three workers on two GPUs map to `cuda:0, cuda:1, cuda:0`. Each worker holds a model copy; more workers on one device increase memory use and may not be faster. Fewer workers than devices use the first devices and log idle ones. CPU workers have a thread budget. Two MPS workers on Apple M2 Max have been tested with real COCO samples; other systems, CUDA, and multi-GPU performance require measurement.

### Logs

`serve`, `serve --api-only`, `ui`, `segment`, `detect`, and `boxes-from-masks` create a session log at `~/.cache/annodesk/YYYY-MM-DD_HHMMSS_ffffff.log`, including on macOS. Use `--log-dir /path/to/logs --log-level DEBUG` to change location and terminal/file level. INFO is the default, with 20MB rotation and 14-day retention. An unwritable directory produces a warning and falls back to terminal/in-memory logs without affecting annotation saves. Help, docs, doctor, and models queries do not create log files.

**Logs** opens a resizable central window, available even without a project. It shows time, level, and important model/device/worker READY/task/error messages without filenames, line numbers, or stack traces. Choose Service or Current project, and filter by `=` (only that level) or `≥` (that level and above), including SUCCESS. Pause/resume, auto-scroll, clear view, copy view, and downloading the current log file are available. Routine polling, per-box inference, and autosave do not flood the view. Repeated errors are grouped; files and reports retain original diagnostics.

The page displays at most 1,000 entries and warns when older logs are no longer available. Consult log files for full history. Pausing/closing the window does not stop tasks or file logging. With separate hosts, backend logs stay on the backend. A standalone CLI run has its own session file and does not appear in another backend's live Logs. A UI-only process logs locally, while the page's Logs connects to the configured API.

## 7. Keyboard shortcuts

Single-key shortcuts are suppressed inside inputs, class search, and IME composition. Open **? / Shortcuts** at the top right to search mappings. Hover hints appear after about 150ms.

| Action | Keys |
| --- | --- |
| Previous / next image | A / D or ← / → |
| Select / detection box | V / R |
| Positive / negative point | Q / E |
| SAM box prompt / text prompt | B / T |
| Start the next object | N |
| Refine the selected mask | Enter |
| New line in a text prompt | Enter inside the input |
| Preview text segmentation | Ctrl+Enter or ⌘Enter |
| Apply / cancel candidates | Enter / Esc |
| Switch candidates | ← / → with the candidate strip focused |
| Change class | C or double-click an instance |
| Navigate the class picker | ↑ / ↓, Enter, Esc |
| Delete selected geometry, prompt, or instance | X or Delete or Backspace |
| Delete the whole instance and its prompts | Shift+X or Shift+Delete |
| Clear selection / close the current window | Esc |
| Temporary pan | Hold Space |
| Fit image | F |
| Zoom in | + or = |
| Zoom out | - |
| Zoom around the cursor | Mouse wheel |
| Approve / needs review / toggle exclusion | 1 / 2 / 3 |
| Undo | Ctrl+Z or ⌘Z |
| Redo | Ctrl+Shift+Z or ⌘Shift+Z |
| Save | Ctrl+S or ⌘S |
| Show shortcuts | ? |

## 8. Deployment and browser addresses

Dataset paths are resolved by **the computer running `serve`, including `--api-only`**. Images, labels, project records, and models must be on that machine or in a shared/mounted directory it can read and write. Project paths and saved labels belong to that backend.

| Command | Where it runs | What it serves | Browser address |
| --- | --- | --- | --- |
| `serve` | The dataset/inference computer | API and annotation page | `http://127.0.0.1:8765` locally, or `http://SERVER_IP:8765` remotely |
| `serve --api-only` | The dataset/inference computer | API only | Host the page separately and open its address |
| `ui` | The web-page host, possibly your laptop | Page and API address configuration | `http://127.0.0.1:8080` on that machine; the browser calls `--api-url` directly |

### Annotation and inference on one computer

Run on the dataset computer:

```sh
annodesk serve --project /data/my-dataset --open
```

Browse `http://127.0.0.1:8765`. `--open` launches a browser on the computer executing the command.

### Full service on a GPU server, local browser access (recommended)

Run on the GPU server:

```sh
annodesk serve --host 0.0.0.0 --port 8765 --project /srv/datasets/my-dataset
```

Open `http://SERVER_IP:8765` in your own computer's browser. No local `ui` command is needed; the server already hosts the page. The dataset path, model directories, and `HF_MODELS` in this example all belong to the server.

### Separate web hosting with the API on a GPU server

Separate hosting is useful for independent page deployment, frontend/backend development, or other API clients. `serve --api-only` provides only the API and cannot be combined with `--open`.

On the GPU server:

```sh
annodesk serve --api-only --host 0.0.0.0 --port 8765 --project /srv/datasets/my-dataset
```

On your own computer, with AnnoDesk installed:

```sh
annodesk ui --api-url http://SERVER_IP:8765 --port 8080
```

Browse `http://127.0.0.1:8080` locally. The page directly requests `http://SERVER_IP:8765/api/v1`, so that address must be reachable from the browser computer. `ui` does not proxy dataset reads/writes or perform inference.

To expose the UI host to other computers, add `--host 0.0.0.0` to `ui` and browse `http://UI_HOST_IP:8080`. `0.0.0.0` is a bind address, not a browser destination. `127.0.0.1` always means the local computer for the browser or command using it.

### Can a local dataset use only a remote server's compute?

**The current version does not support opening a local dataset, uploading images/prompts to a remote inference-only server, and saving returned results locally.** Running the API on a server and `ui` on your laptop does not provide this workflow. The server still reads and writes the dataset.

If data is on your laptop, synchronize it to the server or expose it through a shared/mounted directory. Use the path visible to the server. Entering a path in the browser does not upload or map local files.

In a source environment, prefix commands with `uv run`, such as `uv run annodesk serve`. Host roles and data ownership remain the same. The current service has no authentication; use HTTP deployment on a trusted network.

## 9. Troubleshooting

| Symptom | What to do |
| --- | --- |
| Missing styling, old CSS/JS returning 404, or a problem in only one browser after upgrading | Save edits, restart the new version, and hard-refresh (Ctrl+Shift+R on Windows/Linux; ⌘Shift+R on macOS). If needed, clear only this site's cache. Browsers have separate caches. |
| Open project notice | Open a dataset or pass `--project` at startup; this is not a service failure. |
| Port already in use | Select another `--port` or stop the other service. |
| Model shows missing | Check the JSON path, directory resolution, backend, and top-level weights, then Reload. |
| No compatible .pt checkpoint | Prepare compatible local weights; the adapter does not download or convert them automatically. |
| Multiple checkpoint candidates | Keep each model in a separate directory with an unambiguous checkpoint. |
| Missing ultralytics / torch / tokenizer | Install the dependencies explicitly in the backend environment and restart. Use `annodesk doctor` to help inspect dependencies. |
| Project is in use | Stop the other AnnoDesk service/CLI holding that project; do not bypass the lock by deleting its file. |
| Model load failure or insufficient device memory | Inspect Logs and Tasks, reduce workers or choose a smaller model, and start a new batch. Devices do not silently change. |
| Save conflict | Keep the page and a backup, inspect external edits, and compare files before proceeding. |
| New edits exist when inference completes | The page preserves the newer edits and reports the conflict. Back up and inspect the state before reloading or retrying. |
| Fewer exported images than the project total | Check the selected task's review states, Excluded, unassigned classes, and empty-image confirmation. |
| Unsupported model or inference error | Manual box annotation remains available. Record model format, dependency versions, and the console error for diagnosis. |

## 10. Commands and help

Every command's `--help` explains its parameters and omitted/default behavior. `(default: None)` means an optional value was not supplied; normally omit the argument rather than entering `None`.

| Option | Behavior when omitted |
| --- | --- |
| `serve --project` | Start without a project; open one from the workbench later. |
| `--models-config` | Check `ANNODESK_MODELS_CONFIG`, current-directory `models.json`, then the default preset. |
| `--log-dir` | Write logs to `~/.cache/annodesk/`. |
| `docs --output` | Print the guide to the terminal without creating a file. |
| `docs --lang` | Show the English guide; use `zh-CN` for Simplified Chinese. |
| `detect --model-classes` | Consider all model classes, subject to project compatibility. |
| `segment/detect --model` | Use the corresponding task's configured default model. |

| Purpose | Command |
| --- | --- |
| Start the workbench | `annodesk serve` |
| Segment existing boxes | `annodesk segment` |
| Generate detection boxes | `annodesk detect` |
| Create boxes from masks | `annodesk boxes-from-masks` |
| Separate API / UI hosting | `annodesk serve --api-only` / `annodesk ui` |
| List configured local models | `annodesk models list` |
| Check installed inference dependencies | `annodesk doctor` |
| Read or save the guide | `annodesk docs` |

```sh
annodesk docs
annodesk docs --lang zh-CN
annodesk docs --output ./AnnoDesk-user-guide.md
annodesk docs --lang zh-CN --output ./AnnoDesk-user-guide-cn.md
annodesk --help
annodesk segment --help
annodesk detect --help
annodesk boxes-from-masks --help
```

Both English (`user-guide.md`) and Simplified Chinese (`user-guide-cn.md`) guides are included in the package. `annodesk docs` prints the English guide for the installed version; `--lang zh-CN` selects Chinese. `--output` saves a Markdown copy and refuses to overwrite an existing file. Reading either guide requires no GitHub access. After upgrading, use this command to obtain the matching instructions.

## 11. Workbench and annotation controls

### Instance list and image properties

The canvas has a single top toolbar for model settings, current-image processing, automatic processing, pan, zoom, and Fit. The upper-right instance list has fixed columns for box, mask, SAM prompts, visibility, lock, and more. Missing geometry keeps a disabled gray slot. The Objects region stays open; each instance's details start collapsed. Clicking its name toggles details while retaining selection. Clicking a geometry icon selects that target and expands details. Visibility/lock controls do not change selection.

Expanded details provide searchable class assignment, mask refinement, candidates, prompt clearing, mask-to-box conversion, prompt details, and box coordinates. Individual points or prompt boxes can be selected through prompt details. More and right-click open the same menu. Locked instances cannot be directly modified or deleted. Metadata/statistics refreshes preserve zoom, pan, instance search, and expanded details.

Three buttons above object search act on the whole image:

- **Clear labels…** confirms deletion of instances and their boxes, masks, and prompts. Locked instances are retained unless explicitly included. One undo restores the operation. Tags, notes, project classes, and exclusion remain; both task review states return to Not reviewed and empty confirmations are cleared.
- **Clear prompts** removes unlocked points/prompt boxes while retaining masks and detection boxes. It supports undo and does not trigger segmentation.
- **Masks to boxes** adds missing detection boxes to unlocked instances and preserves existing boxes.

Image properties occupy the lower-right region. Drag the middle divider to adjust the split (55% by default, 25%–75% range); when focused, use ↑ / ↓, or double-click to reset. Both regions scroll independently. The properties button at the far right of the canvas toolbar toggles the inspector; narrow windows provide Image details.

### Selection, prompts, and box padding

Result selection and SAM prompt selection are separate. **V** restores ordinary selection, unless typing in an input. Tool cursors add badges to the arrow tip: a blue solid rectangle for detection boxes, amber corners with a plus for SAM prompt boxes, and plus/minus/T for points/text. Pan uses a hand; hold Space for temporary panning.

Text prompts float inside the canvas without resizing it. The input defaults to five lines and can be resized vertically. Enter inserts a newline; Ctrl+Enter or ⌘Enter previews; Esc or close returns to ordinary selection.

When deriving boxes from masks, set per-side padding in pixels or as a proportion of the tight mask bounds' width/height. With **min** checked, each axis uses the smaller of its pixel and proportional padding. Results are clipped to image boundaries. Padding defaults to zero. The UI uses percentages; CLI/API use fractions, so `--box-padding-ratio 0.1` means 10% on each side. CLI options are `--box-padding-mode pixels|ratio`, `--box-padding-pixels`, `--box-padding-ratio`, and `--box-padding-min`. Instance, current-image, and batch geometry operations share session settings; launched tasks retain their parameter snapshot.

**Auto-segment** defaults on and fills eligible missing masks for non-excluded, segmentation-unreviewed images when a model is available. It preserves existing masks. **Auto-detect** defaults off.

### Review and statistics

The permanent bar shows Approved/total and four mutually exclusive counts: Not reviewed, Approved, Needs review, Excluded. Needs review and Excluded do not contribute to Approved. Box/mask totals count saved manual and generated results, excluding excluded images by default. SAM prompt boxes are not detection boxes; an instance with both a box and a mask contributes to both counts.

**More statistics** opens a central window with class search, a table/bar-chart switch, and an option to include excluded images' geometry. That option does not change the review denominator. Tables include distinct images and instances per class. Unassigned instances have their own row, and unused classes show zero. Results sort by combined box/mask counts, with 50 rows per table page or 20 per chart page. Unreadable annotations are reported rather than counted as empty labels.

An image without current-task annotations can remain Not reviewed, be marked Needs review, or be excluded. Approval requires labels or explicit confirmation that no objects are present. **Confirm no objects for this task** sits below review buttons and above tags/notes. Confirmation and approval are separate actions. Removing empty confirmation from an otherwise empty Approved image returns it to Not reviewed. Invalid approvals left by older versions are not silently rewritten, but still must satisfy export requirements.

### Export confirmation and skip reasons

Export first computes a summary; **Confirm export** starts writing. Both the main summary and Skipped images group counts by the four review states. Nested **No valid annotations** counts refer to images without valid task labels and without explicit empty confirmation. They are subsets of their parent counts, not extra images. Confirmed-empty images can be exported as negative samples. Inputs with unreadable review states appear separately.

Skip details expand when images are skipped. A separate scroll area lists up to 100 relative paths and short reasons, showing the displayed count and total. Invalid input must be corrected before exporting.

Choose a new directory on the backend; relative paths use the project root. Export creates a separate dataset directory with images, labels, and metadata, not a browser download. If source image versions, labels, or classes changed after the summary, refresh and confirm again.

If unchanged data/options already have an intact export, the window shows **Already exported** and its path instead of generating a duplicate. Choosing another new destination can create another copy. Deleted or modified outputs are not reused. Existing directories are never overwritten. Failure/cancellation cleans only the current incomplete new directory; cancelling reuse also preserves the earlier dataset.

### Windows, tasks, and errors

Classes, Tags, Models, Tasks, Logs, Statistics, Shortcuts, Batch, and Export use temporary central windows with internal scrolling. Close them to continue annotation; workbench shortcuts are suspended while a window is open. Tasks opens automatically on start. Closing it keeps work running, and the toolbar reopens it. Completion does not steal focus. Closing Logs does not stop file logging.

Ordinary errors use a fixed top-center notification without moving the canvas. It can be dismissed, long messages can expand, and unsaved changes offer Retry save. Blocked actions such as approving an unannotated image use a dialog. **Open image properties** only locates the empty-confirmation control; it never checks it or approves the image automatically.

## 12. License

AnnoDesk's original source is MIT licensed. The bundled YOLO11n weights come from Ultralytics and retain their original license and source notices; they are not covered by AnnoDesk's MIT license. Other models and dependencies retain their respective licenses.
