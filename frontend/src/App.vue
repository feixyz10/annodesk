<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from "vue";
import {
  NConfigProvider,
  NDrawer,
  NDrawerContent,
  NModal,
  NButton,
} from "naive-ui";
import { configureApi, request, type ProjectMeta, type Category } from "./api";
import { useProject } from "./stores/project";
import AnnotationCanvas from "./components/AnnotationCanvas.vue";
import ImageList from "./components/ImageList.vue";
import ClassPalette from "./components/ClassPalette.vue";
import FilmStrip from "./components/FilmStrip.vue";
import Icon from "./components/Icon.vue";
import FastTooltip from "./components/FastTooltip.vue";
import ClassPicker from "./components/ClassPicker.vue";
import { reviewStates } from "./review";
const store = useProject(),
  canvas = ref<InstanceType<typeof AnnotationCanvas>>(),
  openDialog = ref(false),
  path = ref(""),
  classesOpen = ref(false),
  tagsOpen = ref(false),
  help = ref(false),
  promptText = ref(""),
  keySearch = ref("");
const left = ref(Number(localStorage.getItem("lb-left")) || 260),
  right = ref(Number(localStorage.getItem("lb-right")) || 290),
  top = ref(Number(localStorage.getItem("lb-top")) || 53);
const shortcuts = [
  ["Previous / next image", "A / D or ← / →"],
  ["Select / draw box", "V / R"],
  ["Positive / negative point", "Q / E"],
  ["Box / text prompt", "B / T"],
  ["Accept segmentation", "Enter"],
  ["Fit image", "F"],
  ["Pan", "Hold Space"],
  ["Zoom in / out", "+ / -"],
  ["Approve / needs review / exclude", "1 / 2 / 3"],
  ["Change selected annotation class", "C or double-click"],
  ["Delete selected", "X or Delete"],
  ["Undo", "Ctrl+Z or ⌘Z"],
  ["Redo", "Ctrl+Shift+Z or ⌘Shift+Z"],
  ["Save", "Ctrl+S or ⌘S"],
  ["Shortcuts", "?"],
];
const tools = [
  ["select", "Select", "V"],
  ["box", "Draw box", "R"],
  ["positive", "Positive point", "Q"],
  ["negative", "Negative point", "E"],
  ["promptbox", "Box prompt: mask only", "B"],
  ["text", "Text prompt (SAM 3)", "T"],
  ["pan", "Pan", "Space"],
];
async function openProject() {
  await store.open(path.value);
  if (store.meta) openDialog.value = false;
}
async function update(c: Category) {
  try {
    await request("/categories/" + c.id, "PATCH", c);
  } catch (e) {
    store.error = String(e);
  }
}
function resize(e: PointerEvent, side: string) {
  const startX = e.clientX,
    startY = e.clientY,
    initial =
      side === "left" ? left.value : side === "right" ? right.value : top.value;
  const move = (event: PointerEvent) => {
    if (side === "top")
      top.value = Math.max(
        25,
        Math.min(
          75,
          initial + ((event.clientY - startY) / (innerHeight - 90)) * 100,
        ),
      );
    else if (side === "left")
      left.value = Math.max(
        190,
        Math.min(460, initial + event.clientX - startX),
      );
    else
      right.value = Math.max(
        220,
        Math.min(460, initial - event.clientX + startX),
      );
  };
  const done = () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", done);
    localStorage.setItem(
      "lb-" + side,
      String(
        side === "left"
          ? left.value
          : side === "right"
            ? right.value
            : top.value,
      ),
    );
  };
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", done, { once: true });
}
function review(value: string) {
  if (!store.annotation) return;
  store.checkpoint();
  if (value === "excluded")
    store.annotation.excluded = !store.annotation.excluded;
  else
    store.annotation[
      store.task === "detection" ? "detection_review" : "segmentation_review"
    ] = value as "ok" | "pending" | "uncertain";
  store.changed();
}
async function tags(value: string) {
  if (!store.annotation) return;
  store.annotation.tags = [
    ...new Set(
      value
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean),
    ),
  ];
  store.changed();
  for (const name of store.annotation.tags)
    if (!store.meta?.tags.some((c) => c.name === name)) {
      try {
        const c = await request<Category>("/tags", "POST", { name });
        store.meta?.tags.push(c);
      } catch (e) {
        store.error = String(e);
      }
    }
}
function key(e: KeyboardEvent) {
  if (
    store.navigating ||
    e.isComposing ||
    (e.target as HTMLElement).closest(
      "input,textarea,select,[contenteditable=true]",
    ) ||
    openDialog.value ||
    classesOpen.value ||
    tagsOpen.value ||
    help.value ||
    store.classPickerOpen
  )
    return;
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
    e.preventDefault();
    void store.save();
    return;
  }
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z") {
    e.preventDefault();
    store.undo(e.shiftKey);
    return;
  }
  if (e.ctrlKey || e.metaKey || e.altKey) return;
  if (
    (e.target as HTMLElement).closest("button") &&
    ["Enter", " "].includes(e.key)
  )
    return;
  const k = e.key.toLowerCase();
  if (k === "a" || k === "arrowleft") {
    e.preventDefault();
    store.move(-1);
  } else if (k === "d" || k === "arrowright") {
    e.preventDefault();
    store.move(1);
  } else if (k === "c") {
    e.preventDefault();
    store.openClassPicker();
  } else if (k === "f") canvas.value?.fit();
  else if (k === "+" || k === "=") canvas.value?.zoom(1.25);
  else if (k === "-") canvas.value?.zoom(0.8);
  else if (k === "x" || k === "delete" || k === "backspace") {
    e.preventDefault();
    store.remove();
  } else if (k === "?") help.value = true;
  else if (k === "escape") store.selected = null;
  else if (k === "enter") void store.segment();
  else if (["1", "2", "3"].includes(k))
    review({ "1": "ok", "2": "uncertain", "3": "excluded" }[k]!);
  else if (
    {
      v: "select",
      r: "box",
      q: "positive",
      e: "negative",
      b: "promptbox",
      t: "text",
    }[k]
  )
    store.tool = {
      v: "select",
      r: "box",
      q: "positive",
      e: "negative",
      b: "promptbox",
      t: "text",
    }[k]!;
}
async function exportCurrent() {
  try {
    await store.save();
    const r = await request<{ path: string }>("/export", "POST", {
      task: store.task,
    });
    store.error = "Export saved on backend: " + r.path;
  } catch (e) {
    store.error = String(e);
  }
}
async function reindex() {
  try {
    await store.save();
    await request("/classes/reindex", "POST", {});
    await store.refresh();
    if (store.current) await store.load(store.current);
  } catch (e) {
    store.error = String(e);
  }
}
const jobsOpen = ref(false),
  jobs = ref<
    Array<{
      id: string;
      status: string;
      completed: number;
      skipped: number;
      total: number;
      failed: Array<{ image: string; error: string }>;
    }>
  >([]);
let jobsTimer: ReturnType<typeof setInterval>;
async function refreshJobs() {
  if (!jobsOpen.value || !store.meta) return;
  try {
    jobs.value = await request("/jobs");
  } catch (e) {
    store.error = String(e);
  }
}
async function startBatch() {
  try {
    await store.save();
    await request("/jobs", "POST", { model: store.model });
    jobsOpen.value = true;
    await refreshJobs();
  } catch (e) {
    store.error = String(e);
  }
}
async function jobAction(id: string, resume = false) {
  try {
    await request(
      "/jobs/" + id + (resume ? "/resume" : ""),
      resume ? "POST" : "DELETE",
    );
    await refreshJobs();
  } catch (e) {
    store.error = String(e);
  }
}
function createClass() {
  const name = window.prompt("New class name");
  if (name) void store.addClass(name);
}
function unload(e: BeforeUnloadEvent) {
  if (store.dirty || store.saving) {
    e.preventDefault();
    e.returnValue = "";
  }
}
onMounted(async () => {
  await configureApi();
  await store.refreshModels();
  jobsTimer = setInterval(() => void refreshJobs(), 1000);
  try {
    await store.refresh();
    if (store.images[0]) await store.load(store.images[0]);
  } catch (e) {
    store.error = String(e);
  }
  window.addEventListener("keydown", key);
  window.addEventListener("beforeunload", unload);
});
onBeforeUnmount(() => {
  clearInterval(jobsTimer);
  window.removeEventListener("keydown", key);
  window.removeEventListener("beforeunload", unload);
});
</script>
<template>
  <NConfigProvider
    ><div class="app" :inert="store.navigating">
      <header>
        <strong class="brand"
          ><img
            src="/annodesk.svg"
            alt=""
            width="28"
            height="28"
          />AnnoDesk</strong
        ><button
          @click="
            path = store.meta?.root ?? '';
            openDialog = true;
          "
          title="Open a dataset or image folder on the backend"
        >
          {{
            store.meta ? store.meta.root.split("/").at(-1) : "Open project…"
          }}</button
        ><span class="grow"></span
        ><button
          title="Manage project class names, colors and IDs. Use the palette to assign annotations."
          @click="classesOpen = true"
        >
          Manage classes</button
        ><button
          title="Manage project tag names and colors"
          @click="tagsOpen = true"
        >
          Tags</button
        ><button
          class="primary"
          title="Segment existing boxes without a mask in the current image"
          :disabled="!store.meta"
          @click="store.segment(true)"
        >
          Segment current</button
        ><button
          title="Segment existing boxes across the dataset"
          :disabled="!store.meta"
          @click="startBatch"
        >
          Batch…</button
        ><button
          title="Export reviewed annotations for the current task"
          :disabled="!store.meta"
          @click="exportCurrent"
        >
          Export</button
        ><button title="Keyboard shortcuts · ?" @click="help = true">
          Shortcuts ?
        </button>
      </header>
      <div v-if="store.error" class="alert" role="alert">
        {{ store.error }}<button @click="store.error = ''">Dismiss</button
        ><button v-if="store.dirty" @click="store.save().catch(() => {})">
          Retry save
        </button>
      </div>
      <main
        class="workspace"
        :style="{ '--left': left + 'px', '--right': right + 'px' }"
      >
        <aside class="left-panel">
          <div class="images-pane" :style="{ height: top + '%' }">
            <ImageList />
          </div>
          <div
            class="horizontal split"
            role="separator"
            aria-label="Resize images and classes"
            aria-orientation="horizontal"
            @pointerdown="resize($event, 'top')"
            @dblclick="top = 53"
          ></div>
          <ClassPalette />
        </aside>
        <div
          class="split"
          role="separator"
          aria-label="Resize left panel"
          aria-orientation="vertical"
          @pointerdown="resize($event, 'left')"
          @dblclick="left = 260"
        ></div>
        <nav class="tools">
          <button
            v-for="[id, title, key] in tools"
            :key="id"
            :title="title + ' · ' + key"
            :aria-label="title"
            :class="{ active: store.tool === id }"
            @click="store.tool = id"
          >
            <Icon :name="id" /></button
          ><button title="Undo · Ctrl+Z or ⌘Z" @click="store.undo()">↶</button>
        </nav>
        <section class="center">
          <div class="canvasbar">
            <select
              v-model="store.model"
              aria-label="Segmentation model"
              :title="
                store.models?.models.find((m) => m.id === store.model)?.error ||
                'Local segmentation model. No automatic downloads.'
              "
            >
              <option
                v-for="m in store.models?.models ?? []"
                :key="m.id"
                :value="m.id"
              >
                {{ m.name }}{{ m.available ? "" : " (missing)" }}
              </option>
            </select>
            <button
              title="Reload models.json and check local model files"
              @click="store.refreshModels()"
            >
              Reload
            </button>
            <label title="Only boxes without a mask are processed"
              ><input type="checkbox" v-model="store.autoSegment" />
              Auto-segment</label
            ><span class="grow"></span
            ><button
              aria-label="Zoom out"
              title="Zoom out · -"
              @click="canvas?.zoom(0.8)"
            >
              <Icon name="minus" /></button
            ><span class="zoom"
              >{{ Math.round((canvas?.ratio ?? 1) * 100) }}%</span
            ><button
              aria-label="Zoom in"
              title="Zoom in · +"
              @click="canvas?.zoom(1.25)"
            >
              <Icon name="plus" /></button
            ><button
              aria-label="Fit image"
              title="Fit image · F"
              @click="canvas?.fit()"
            >
              <Icon name="fit" />
            </button>
          </div>
          <div v-if="store.tool === 'text'" class="textbar">
            <input
              v-model="promptText"
              placeholder="English target description…"
            /><button @click="store.segment(false, promptText)">
              Preview text segmentation
            </button>
          </div>
          <AnnotationCanvas ref="canvas" />
          <div v-if="!store.current" class="empty">
            <h2>Open an image dataset</h2>
            <p>Start with images or import existing YOLO boxes.</p>
            <NButton type="primary" @click="openDialog = true"
              >Open project</NButton
            >
          </div>
          <div class="imagebar">
            {{ store.current?.path ?? "No image selected"
            }}<span
              >{{ store.annotation?.width }} ×
              {{ store.annotation?.height }}</span
            >
          </div>
          <FilmStrip />
        </section>
        <div
          class="split"
          role="separator"
          aria-label="Resize right panel"
          aria-orientation="vertical"
          @pointerdown="resize($event, 'right')"
          @dblclick="right = 290"
        ></div>
        <aside class="right-panel">
          <div class="section">
            <strong>Current image</strong>
            <p class="muted ellipsis" :title="store.current?.path">
              {{ store.current?.path ?? "—" }}
            </p>
            <div class="row">
              <button
                v-for="task in ['detection', 'segmentation'] as const"
                :class="{ active: store.task === task }"
                @click="store.task = task"
              >
                {{ task }}
              </button>
            </div>
          </div>
          <template v-if="store.annotation"
            ><div class="section">
              <h3>Image review</h3>
              <div class="review">
                <button
                  v-for="{ value, label } in reviewStates"
                  :class="{
                    active:
                      value === 'excluded'
                        ? store.annotation.excluded
                        : store.annotation[
                            store.task === 'detection'
                              ? 'detection_review'
                              : 'segmentation_review'
                          ] === value,
                  }"
                  @click="review(value)"
                >
                  {{ label }}
                </button>
              </div>
              <div class="tag-chips">
                <span
                  v-for="tag in store.annotation.tags"
                  :style="{
                    borderColor: store.meta?.tags.find((c) => c.name === tag)
                      ?.color,
                  }"
                  >{{ tag }}</span
                >
              </div>
              <input
                :value="store.annotation.tags.join(', ')"
                placeholder="Image tags, comma separated"
                @change="tags(($event.target as HTMLInputElement).value)"
              /><textarea
                v-model="store.annotation.notes"
                placeholder="Image notes…"
                @change="store.changed()"
              ></textarea
              ><label
                ><input
                  type="checkbox"
                  v-model="store.annotation.explicit_empty[store.task]"
                  @change="store.changed()"
                />
                Confirm no objects for this task</label
              >
            </div>
            <div class="section">
              <div class="row">
                <h3>Objects</h3>
                <span class="muted">{{
                  store.annotation.instances.length
                }}</span>
              </div>
              <button
                v-for="object in store.annotation.instances"
                :key="object.id"
                class="object-row"
                :class="{ active: object.id === store.selected }"
                @click="store.selected = object.id"
              >
                <i
                  :style="{
                    background:
                      store.meta?.classes.find((c) => c.id === object.class_id)
                        ?.color ?? '#888',
                  }"
                ></i
                ><span>{{
                  store.meta?.classes.find((c) => c.id === object.class_id)
                    ?.name ?? "Unassigned"
                }}</span
                ><small
                  >{{ object.box ? "Box" : "" }}
                  {{ object.polygons.length ? "Mask" : "" }}</small
                ></button
              ><template v-if="store.object"
                ><button
                  title="Search and assign a class · C"
                  :disabled="store.object.locked"
                  @click="store.openClassPicker()"
                >
                  Change class <kbd>C</kbd>
                </button>
                <select
                  :disabled="store.object.locked"
                  title="Assign a class to the selected annotation"
                  v-model="store.object.class_id"
                  @change="store.changed(true)"
                >
                  <option :value="null">Unassigned</option>
                  <option v-for="c in store.meta?.classes" :value="c.id">
                    {{ c.name }}
                  </option>
                </select>
                <div v-if="store.object.box" class="coords">
                  <label v-for="(_, i) in store.object.box"
                    >{{ ["x1", "y1", "x2", "y2"][i]
                    }}<input
                      type="number"
                      v-model.number="store.object.box[i]"
                      @change="store.changed(true)"
                  /></label>
                </div>
                <div class="row">
                  <label
                    ><input
                      type="checkbox"
                      v-model="store.object.locked"
                      @change="store.changed()"
                    />
                    Locked</label
                  ><label
                    ><input
                      type="checkbox"
                      v-model="store.object.hidden"
                      @change="store.changed()"
                    />
                    Hidden</label
                  >
                </div>
                <div class="row">
                  <button
                    title="Delete selected annotation · X or Delete"
                    @click="store.remove()"
                  >
                    Delete object</button
                  ><button @click="store.segment()">Refine mask</button>
                </div></template
              >
              <p v-else class="muted">
                Select an object to inspect or edit it.
              </p>
            </div></template
          >
        </aside>
      </main>
      <footer>
        <span>{{ store.tool }}</span
        ><span>A / D or ← / →: previous / next image</span
        ><span class="grow"></span
        ><span :class="{ warning: store.dirty }">{{
          store.saving ? "Saving…" : store.dirty ? "Unsaved changes" : "Saved"
        }}</span>
      </footer>
      <NModal
        v-model:show="openDialog"
        preset="card"
        title="Open project"
        style="width: 520px"
        ><p>
          Enter a folder path on the backend machine. An images subfolder and
          data.yaml are optional.
        </p>
        <input
          v-model="path"
          placeholder="/path/to/dataset"
          @keydown.enter="openProject"
        />
        <div class="row" style="margin-top: 16px">
          <NButton type="primary" @click="openProject">Open</NButton>
        </div></NModal
      >
      <NDrawer v-model:show="jobsOpen" :width="440"
        ><NDrawerContent title="Batch segmentation" closable
          ><p>Completed images remain saved if this page disconnects.</p>
          <section v-for="job in jobs" :key="job.id" class="section">
            <strong>{{ job.status }}</strong>
            <p>
              {{ job.completed }} / {{ job.total }} processed ·
              {{ job.skipped }} skipped · {{ job.failed.length }} failed
            </p>
            <progress
              :value="job.completed"
              :max="job.total"
              style="width: 100%"
            ></progress
            ><button v-if="job.status === 'running'" @click="jobAction(job.id)">
              Cancel after current image</button
            ><button
              v-else-if="job.status !== 'complete'"
              @click="jobAction(job.id, true)"
            >
              Resume
            </button>
            <p v-for="failure in job.failed.slice(-3)" class="muted">
              {{ failure.error }}
            </p>
          </section></NDrawerContent
        ></NDrawer
      >
      <NDrawer v-model:show="classesOpen" :width="390"
        ><NDrawerContent title="Project classes" closable
          ><p>
            Manage names and colors. Use the class palette to assign
            annotations.
          </p>
          <div v-for="c in store.meta?.classes" class="category-editor">
            <input type="color" v-model="c.color" @change="update(c)" /><input
              v-model="c.name"
              @change="update(c)"
            /><span>ID {{ c.index }}</span>
          </div>
          <button @click="createClass">Add class</button
          ><button @click="reindex">Reindex IDs…</button></NDrawerContent
        ></NDrawer
      >
      <NDrawer v-model:show="tagsOpen" :width="390"
        ><NDrawerContent title="Project tags" closable>
          <section class="tag-group" aria-labelledby="builtin-states-heading">
            <div class="row">
              <h3 id="builtin-states-heading">Built-in review states</h3>
              <span class="readonly-label">Read only</span>
            </div>
            <p class="muted">
              Review is tracked per task. Excluded applies to the whole image.
            </p>
            <ul class="builtin-states">
              <li v-for="state in reviewStates" :key="state.value">
                <i :style="{ background: state.color }" aria-hidden="true"></i>
                <div>
                  <strong>{{ state.label }}</strong>
                  <p class="muted">{{ state.description }}</p>
                </div>
              </li>
            </ul>
          </section>
          <section class="tag-group" aria-labelledby="custom-tags-heading">
            <h3 id="custom-tags-heading">Custom image tags</h3>
            <p v-if="!store.meta?.tags.length" class="muted">
              No custom tags yet.
            </p>
            <div v-for="c in store.meta?.tags" class="category-editor">
              <input type="color" v-model="c.color" @change="update(c)" /><input
                v-model="c.name"
                @change="update(c)"
              />
            </div>
            <p class="muted">
              New tags are registered when added to an image. Their names and
              colors are editable here.
            </p>
          </section></NDrawerContent
        ></NDrawer
      >
      <NDrawer v-model:show="help" :width="420"
        ><NDrawerContent title="Keyboard shortcuts" closable
          ><input v-model="keySearch" placeholder="Search actions or keys…" />
          <div
            v-for="[action, key] in shortcuts.filter((row) =>
              row.join(' ').toLowerCase().includes(keySearch.toLowerCase()),
            )"
            class="shortcut"
          >
            <span>{{ action }}</span
            ><kbd>{{ key }}</kbd>
          </div>
          <p>Single-key shortcuts are disabled while typing.</p></NDrawerContent
        ></NDrawer
      >
      <ClassPicker />
      <FastTooltip /></div
  ></NConfigProvider>
</template>
