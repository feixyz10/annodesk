<script setup lang="ts">
import {
  t,
  locale,
  setLocale,
  taskLabel,
  statusLabel,
  toolLabel,
  uiError,
} from "./i18n";
import {
  onMounted,
  onBeforeUnmount,
  ref,
  computed,
  watch,
  nextTick,
  defineAsyncComponent,
} from "vue";
import {
  NConfigProvider,
  NModal,
  NButton,
  enUS,
  zhCN,
  dateEnUS,
  dateZhCN,
} from "naive-ui";
import { configureApi, request, type ProjectMeta, type Category } from "./api";
import { useProject } from "./stores/project";
import AnnotationCanvas from "./components/AnnotationCanvas.vue";
import ImageList from "./components/ImageList.vue";
import ClassPalette from "./components/ClassPalette.vue";
import CategoryEditor from "./components/CategoryEditor.vue";
import CandidateBar from "./components/CandidateBar.vue";
import FilmStrip from "./components/FilmStrip.vue";
import Icon from "./components/Icon.vue";
import FastTooltip from "./components/FastTooltip.vue";
import ClassPicker from "./components/ClassPicker.vue";
import StatisticsBar from "./components/StatisticsBar.vue";
import ModelNotice from "./components/ModelNotice.vue";
import LogDrawer from "./components/LogDrawer.vue";
const ModelSettings = defineAsyncComponent(
  () => import("./components/ModelSettings.vue"),
);
const BatchSetup = defineAsyncComponent(
  () => import("./components/BatchSetup.vue"),
);
import TaskWindow from "./components/TaskWindow.vue";
import ClearImageAnnotations from "./components/ClearImageAnnotations.vue";
import ExportSetup from "./components/ExportSetup.vue";
import WorkspaceInspector from "./components/WorkspaceInspector.vue";
import { type Job, isPreparing } from "./tasks";
import { reviewStates } from "./review";
import { readPreference, writePreference } from "./preferences";
const store = useProject(),
  canvas = ref<InstanceType<typeof AnnotationCanvas>>(),
  openDialog = ref(false),
  path = ref(""),
  classesOpen = ref(false),
  tagsOpen = ref(false),
  help = ref(false),
  inspectorOpen = ref(false),
  inspectorCollapsed = ref(false),
  promptText = ref(""),
  textPromptInput = ref<HTMLTextAreaElement>(),
  emptyConfirmation = ref<HTMLInputElement>(),
  clearAnnotationsOpen = ref(false),
  exportOpen = ref(false),
  keySearch = ref("");
const approvalWarning = computed(
  () =>
    store.error.replace(/^Error: /, "") ===
    "Add annotations or explicitly confirm no objects before approving this task",
);
let focusEmptyAfterClose = false;
function openApprovalProperties() {
  focusEmptyAfterClose = true;
  inspectorCollapsed.value = false;
  inspectorOpen.value = true;
  store.error = "";
}
async function approvalClosed() {
  if (!focusEmptyAfterClose) return;
  focusEmptyAfterClose = false;
  await nextTick();
  emptyConfirmation.value?.scrollIntoView({ block: "center" });
  emptyConfirmation.value?.focus();
}
const left = ref(Number(readPreference("lb-left")) || 260),
  right = ref(Number(readPreference("annodesk-inspector-width")) || 340),
  top = ref(Number(readPreference("lb-top")) || 53);
watch(
  () => store.tool,
  async (tool) => {
    if (tool === "text") {
      await nextTick();
      textPromptInput.value?.focus();
    }
  },
);
function submitTextPrompt() {
  if (promptText.value.trim() && store.current && !store.navigating)
    void store.segment(false, promptText.value);
}
const shortcuts = [
  ["Previous / next image", "A / D or ← / →"],
  ["Select", "V"],
  ["Detection box", "R"],
  ["Positive point", "Q"],
  ["Negative point", "E"],
  ["SAM box prompt", "B"],
  ["Text prompt (SAM 3)", "T"],
  ["Start a new object", "N"],
  ["Refine selected mask", "Enter"],
  ["Preview text segmentation", "Ctrl+Enter or ⌘Enter"],
  ["New line in text prompt", "Enter (text input focused)"],
  ["Apply / cancel mask candidate", "Enter / Esc"],
  ["Switch candidates (candidate bar focused)", "← / →"],
  ["Class picker navigation", "↑ / ↓, Enter, Esc"],
  ["Change selected annotation class", "C or double-click"],
  ["Delete selected geometry, prompt or object", "X or Delete or Backspace"],
  ["Delete whole object with all prompts", "Shift+X or Shift+Delete"],
  ["Cancel selection or close the active window", "Esc"],
  ["Fit image", "F"],
  ["Pan", "Hold Space"],
  ["Zoom in", "+ or ="],
  ["Zoom out", "-"],
  ["Zoom at pointer", "Mouse wheel"],
  ["Approve current task", "1"],
  ["Mark needs review", "2"],
  ["Toggle excluded", "3"],
  ["Undo", "Ctrl+Z or ⌘Z"],
  ["Redo", "Ctrl+Shift+Z or ⌘Shift+Z"],
  ["Save", "Ctrl+S or ⌘S"],
  ["Shortcuts", "?"],
];
const toolGroups = [
  {
    label: "Labels",
    description:
      "Detection boxes are annotation results and are saved to labels/.",
    items: [["box", "Detection box", "R"]],
  },
  {
    label: "SAM",
    description:
      "SAM prompts guide mask generation; they are not detection labels.",
    items: [
      ["positive", "Positive point", "Q"],
      ["negative", "Negative point", "E"],
      ["promptbox", "SAM box prompt", "B"],
      ["text", "Text prompt (SAM 3)", "T"],
    ],
  },
];

async function openProject() {
  await store.open(path.value);
  if (store.meta) openDialog.value = false;
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
        300,
        Math.min(480, initial - event.clientX + startX),
      );
  };
  const done = () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", done);
    writePreference(
      side === "right" ? "annodesk-inspector-width" : "lb-" + side,
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
  store.setReview(value as "ok" | "pending" | "uncertain" | "excluded");
}
async function tags(value: string) {
  if (!store.annotation) return;
  const project = store.meta?.session ?? store.meta?.id;
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
        if ((store.meta?.session ?? store.meta?.id) !== project) return;
        store.meta?.tags.push(c);
      } catch (e) {
        if ((store.meta?.session ?? store.meta?.id) !== project) return;
        store.error = String(e);
      }
    }
}
function key(e: KeyboardEvent) {
  if (
    document.querySelector(".annodesk-object-menu, .n-modal") ||
    clearAnnotationsOpen.value ||
    exportOpen.value
  )
    return;
  if (e.key === "Escape" && store.tool === "text") {
    store.activateSelection();
    e.preventDefault();
    return;
  }
  if (e.key === "Escape" && inspectorOpen.value) {
    inspectorOpen.value = false;
    e.preventDefault();
    return;
  }
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
    (e.target as HTMLElement).closest(
      ".task-window, .mask-candidates, .statistics-drawer",
    ) ||
    logsOpen.value ||
    batchSettings.value ||
    modelSettings.value ||
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
    !(
      store.candidates &&
      (e.target as HTMLElement).closest("[data-candidate-trigger]")
    ) &&
    ["Enter", " "].includes(e.key)
  )
    return;
  const k = e.key.toLowerCase();
  if (store.candidates && ["enter", "escape"].includes(k)) {
    e.preventDefault();
    if (k === "enter") void store.applyCandidate();
    else if (store.candidates.phase !== "applying") store.cancelCandidates();
    return;
  }
  if (k === "a" || k === "arrowleft") {
    e.preventDefault();
    store.move(-1);
  } else if (k === "d" || k === "arrowright") {
    e.preventDefault();
    store.move(1);
  } else if (k === "v") {
    e.preventDefault();
    store.activateSelection();
  } else if (k === "c") {
    e.preventDefault();
    store.openClassPicker();
  } else if (k === "f") canvas.value?.fit();
  else if (k === "+" || k === "=") canvas.value?.zoom(1.25);
  else if (k === "-") canvas.value?.zoom(0.8);
  else if (k === "x" || k === "delete" || k === "backspace") {
    e.preventDefault();
    if (e.shiftKey && k !== "backspace") store.remove();
    else store.deleteSelected();
  } else if (k === "n") {
    e.preventDefault();
    store.newObject();
  } else if (k === "?") help.value = true;
  else if (k === "escape") store.selected = null;
  else if (k === "enter") void store.segment();
  else if (["1", "2", "3"].includes(k))
    review({ "1": "ok", "2": "uncertain", "3": "excluded" }[k]!);
  else if (
    {
      r: "box",
      q: "positive",
      e: "negative",
      b: "promptbox",
      t: "text",
    }[k]
  )
    store.tool = {
      r: "box",
      q: "positive",
      e: "negative",
      b: "promptbox",
      t: "text",
    }[k]!;
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
  logsOpen = ref(false),
  batchSettings = ref(false),
  modelSettings = ref(false),
  jobs = ref<Job[]>([]);
const currentModel = computed(() =>
  store.models?.models.find(
    (m) =>
      m.id ===
      (store.task === "detection" ? store.detectionModel : store.model),
  ),
);
const currentModelState = computed(() =>
  !currentModel.value?.available
    ? "Unavailable"
    : store.models?.loaded_model === currentModel.value.id
      ? "Loaded"
      : "Available",
);
const taskNotice = ref("");
watch(locale, () => {
  taskNotice.value = "";
});
let noticeTimer: ReturnType<typeof setTimeout> | undefined;
const lastJob = computed(() => jobs.value.at(-1));
const activeJob = computed(() =>
  jobs.value.find((j) => j.status === "running"),
);
let jobsGeneration = 0,
  lastClassRefresh = 0;
watch([() => store.meta?.id, () => store.meta?.session], () => {
  jobsGeneration++;
  jobs.value = [];
  taskNotice.value = "";
  void refreshJobs();
});
let jobsTimer: ReturnType<typeof setInterval>;
async function refreshJobs() {
  if (!store.meta || document.hidden) return;
  const token = ++jobsGeneration,
    project = store.meta.id;
  try {
    const result = await request<Job[]>("/jobs");
    if (token === jobsGeneration && project === store.meta?.id) {
      const previous = new Map(jobs.value.map((j) => [j.id, j.status]));
      jobs.value = result;
      if (
        result.some((j) => j.kind === "detection" && j.status === "running") &&
        Date.now() - lastClassRefresh > 2000
      ) {
        lastClassRefresh = Date.now();
        void store.refreshMeta().catch((e) => (store.error = String(e)));
      }
      const finished = [...result]
        .reverse()
        .find(
          (j) =>
            j.status !== "running" &&
            (!previous.has(j.id) || previous.get(j.id) === "running"),
        );
      if (finished) {
        void store.refreshMeta().catch((e) => (store.error = String(e)));
        void store.refreshCurrent().catch((e) => (store.error = String(e)));
        taskNotice.value = t("{kind} {status} · {count} failed", {
          kind: t(finished.kind === "export" ? "Export" : "Batch"),
          status: statusLabel(finished.status),
          count: finished.failed.length,
        });
        if (noticeTimer) clearTimeout(noticeTimer);
        noticeTimer = setTimeout(() => (taskNotice.value = ""), 6000);
      }
    }
  } catch (e) {
    store.error = String(e);
  }
}
async function batchStarted() {
  jobsOpen.value = true;
  await refreshJobs();
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
  const name = window.prompt(t("New class name"));
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
  if (noticeTimer) clearTimeout(noticeTimer);
  window.removeEventListener("keydown", key);
  window.removeEventListener("beforeunload", unload);
});
</script>
<template>
  <NConfigProvider
    :locale="locale === 'zh-CN' ? zhCN : enUS"
    :date-locale="locale === 'zh-CN' ? dateZhCN : dateEnUS"
    ><div class="app" :inert="store.navigating">
      <header>
        <div
          class="header-cluster project-cluster"
          :aria-label="t('Project management')"
        >
          <strong class="brand"
            ><img
              src="/annodesk.svg"
              alt=""
              width="28"
              height="28"
            />AnnoDesk</strong
          >
          <button
            @click="
              path = store.meta?.root ?? '';
              openDialog = true;
            "
            :title="t('Open a dataset or image folder on the backend')"
          >
            {{
              store.meta
                ? store.meta.root.split("/").at(-1)
                : t("Open project…")
            }}
          </button>
          <button
            :title="
              t(
                'Manage project class names, colors and IDs. Use the palette to assign annotations.',
              )
            "
            @click="classesOpen = true"
          >
            {{ t("Classes") }}
          </button>
          <button
            :title="t('Manage project tag names and colors')"
            @click="tagsOpen = true"
          >
            {{ t("Tags") }}
          </button>
        </div>
        <div
          class="header-cluster processing-cluster"
          :aria-label="t('Dataset operations')"
        >
          <button
            :title="
              t(
                'Detect boxes, segment existing boxes, or create boxes from masks',
              )
            "
            :disabled="!store.meta"
            @click="batchSettings = true"
          >
            {{ t("Batch…") }}
          </button>
          <button
            :title="t('Export reviewed annotations for the current task')"
            :disabled="!store.meta"
            @click="exportOpen = true"
          >
            {{ t("Export") }}
          </button>
        </div>
        <span class="grow" />
        <div
          class="header-cluster diagnostics-cluster"
          :aria-label="t('Tasks and diagnostics')"
        >
          <button
            class="task-button"
            @click="jobsOpen = true"
            :disabled="!store.meta"
            :title="
              t(
                'Batch processing and export progress; closing the window keeps tasks running',
              )
            "
          >
            <span v-if="activeJob" class="task-spinner" aria-hidden="true" />
            {{ t("Tasks")
            }}<span v-if="activeJob">
              · {{ activeJob.completed }}/{{ activeJob.total }}</span
            >
            <span
              v-else-if="lastJob?.failed.length || lastJob?.status === 'failed'"
              class="task-error-badge"
              >{{ lastJob?.failed.length || "!" }}</span
            >
            <progress
              v-if="activeJob"
              class="task-button-progress"
              :value="isPreparing(activeJob) ? undefined : activeJob.completed"
              :max="Math.max(1, activeJob.total)"
              :aria-label="
                activeJob.phase
                  ? statusLabel(activeJob.phase)
                  : t('Task progress')
              "
            />
          </button>
          <button
            @click="logsOpen = true"
            :title="t('Important model, device, worker and error events')"
          >
            {{ t("Logs") }}
          </button>
        </div>
        <button
          class="help-button"
          :title="t('Keyboard shortcuts · ?')"
          :aria-label="t('Shortcuts')"
          @click="help = true"
        >
          <Icon name="help" />
        </button>
        <select
          class="language-select"
          :aria-label="t('Language')"
          :title="t('Interface language')"
          :value="locale"
          @change="setLocale(($event.target as HTMLSelectElement).value)"
        >
          <option value="en">English</option>
          <option value="zh-CN">简体中文</option>
        </select>
      </header>
      <StatisticsBar :active="!!activeJob" />
      <div v-if="taskNotice" class="task-notice" role="status">
        {{ taskNotice }}
        <button
          @click="
            jobsOpen = true;
            taskNotice = '';
          "
        >
          {{ t("Details") }}
        </button>
      </div>
      <LogDrawer v-model:show="logsOpen" />
      <aside v-if="store.error && !approvalWarning" class="alert" role="alert">
        <div class="notice-message">
          <span>{{
            uiError(store.error).length > 160
              ? uiError(store.error).slice(0, 160) + "…"
              : uiError(store.error)
          }}</span>
          <details v-if="uiError(store.error).length > 160">
            <summary>{{ t("Details") }}</summary>
            <p>{{ uiError(store.error) }}</p>
          </details>
        </div>
        <div class="notice-actions">
          <button v-if="store.dirty" @click="store.save().catch(() => {})">
            {{ t("Retry save") }}</button
          ><button @click="store.error = ''">{{ t("Dismiss") }}</button>
        </div>
      </aside>
      <ModelNotice
        :config="store.models"
        :task="store.task"
        :model-id="
          store.task === 'detection' ? store.detectionModel : store.model
        "
        settings-button
        @settings="modelSettings = true"
      />
      <main
        class="workspace"
        :class="{ 'inspector-collapsed': inspectorCollapsed }"
        :style="{ '--left': left + 'px', '--right': right + 'px' }"
      >
        <aside class="left-panel">
          <div class="images-pane" :style="{ height: top + '%' }">
            <ImageList />
          </div>
          <div
            class="horizontal split"
            role="separator"
            :aria-label="t('Resize images and classes')"
            aria-orientation="horizontal"
            @pointerdown="resize($event, 'top')"
            @dblclick="top = 53"
          ></div>
          <ClassPalette />
        </aside>
        <div
          class="split"
          role="separator"
          :aria-label="t('Resize left panel')"
          aria-orientation="vertical"
          @pointerdown="resize($event, 'left')"
          @dblclick="left = 260"
        ></div>
        <nav class="tools" :aria-label="t('Annotation tools')">
          <button
            :title="t('Select · V')"
            :aria-label="t('Select')"
            :class="{
              active:
                store.tool === 'select' && store.selectionTarget === 'results',
            }"
            @click="store.activateSelection()"
          >
            <Icon name="select" />
          </button>
          <button
            :title="t('Edit SAM prompts')"
            :aria-label="t('Edit SAM prompts')"
            :aria-pressed="
              store.tool === 'select' && store.selectionTarget === 'prompts'
            "
            :class="{
              active:
                store.tool === 'select' && store.selectionTarget === 'prompts',
            }"
            @click="store.activateSelection('prompts')"
          >
            <Icon name="promptselect" />
          </button>
          <div
            v-for="group in toolGroups"
            :key="group.label"
            class="tool-group"
            role="group"
            :aria-label="t(group.description)"
          >
            <span class="tool-group-label" :title="t(group.description)">{{
              t(group.label)
            }}</span>
            <button
              v-for="[id, title, key] in group.items"
              :key="id"
              :title="t(title) + ' · ' + key + ' · ' + t(group.description)"
              :aria-label="t(title)"
              :class="{
                active: store.tool === id,
                'prompt-tool': group.label === 'SAM',
              }"
              @click="store.tool = id"
            >
              <Icon :name="id" />
            </button>
          </div>
          <div class="tool-group" role="group" :aria-label="t('History')">
            <span class="tool-group-label">{{ t("History") }}</span>
            <button
              :title="t('Undo · Ctrl+Z or ⌘Z')"
              :aria-label="t('Undo')"
              :disabled="!store.history.length"
              @click="store.undo()"
            >
              <Icon name="undo" />
            </button>
            <button
              :title="t('Redo · Ctrl+Shift+Z or ⌘Shift+Z')"
              :aria-label="t('Redo')"
              :disabled="!store.future.length"
              @click="store.undo(true)"
            >
              <Icon name="redo" />
            </button>
          </div>
        </nav>
        <section class="center">
          <div class="canvasbar">
            <div class="canvas-main-controls">
              <button
                class="model-summary"
                :title="t('Choose a model, load it, and configure inference')"
                @click="modelSettings = true"
              >
                <span class="model-summary-name"
                  >{{ store.task === "detection" ? t("Detector") : t("SAM") }}:
                  {{ currentModel?.name || t("Choose model") }}</span
                >
                <small>{{ t(currentModelState) }}</small>
              </button>
              <button
                class="primary"
                :disabled="
                  !store.meta ||
                  (store.task === 'detection' && !store.detectionModel)
                "
                @click="
                  store.task === 'detection'
                    ? store.detect()
                    : store.segment(true)
                "
              >
                {{
                  store.task === "detection"
                    ? t("Detect current")
                    : t("Segment current")
                }}
              </button>
              <label
                v-if="store.task === 'segmentation'"
                :title="t('Process missing masks when switching images')"
                ><input v-model="store.autoSegment" type="checkbox" />
                {{ t("Auto-segment") }}</label
              >
              <label
                v-else
                :title="t('Detect empty, unreviewed images when switching')"
                ><input
                  v-model="store.autoDetect"
                  type="checkbox"
                  :disabled="!store.detectionModel"
                />
                {{ t("Auto-detect") }}</label
              >
            </div>
            <div
              class="view-tools"
              role="toolbar"
              :aria-label="t('Image view controls')"
            >
              <button
                :aria-label="t('Pan')"
                :title="t('Pan · hold Space for temporary pan')"
                :class="{ active: store.tool === 'pan' }"
                :aria-pressed="store.tool === 'pan'"
                @click="store.tool = store.tool === 'pan' ? 'select' : 'pan'"
              >
                <Icon name="pan" />
              </button>
              <button
                :aria-label="t('Zoom out')"
                :title="t('Zoom out · -')"
                @click="canvas?.zoom(0.8)"
              >
                <Icon name="minus" /></button
              ><span class="zoom"
                >{{ Math.round((canvas?.ratio ?? 1) * 100) }}%</span
              ><button
                :aria-label="t('Zoom in')"
                :title="t('Zoom in · +')"
                @click="canvas?.zoom(1.25)"
              >
                <Icon name="plus" /></button
              ><button
                :aria-label="t('Fit image')"
                :title="t('Fit image · F')"
                @click="canvas?.fit()"
              >
                <Icon name="fit" />
              </button>
            </div>
            <div
              class="inspector-controls"
              role="group"
              :aria-label="t('Properties')"
            >
              <button
                class="inspector-toggle"
                :aria-expanded="inspectorOpen"
                aria-controls="image-details"
                @click="inspectorOpen = !inspectorOpen"
              >
                {{ t("Image details") }}
              </button>
              <button
                class="inspector-collapse-toggle"
                :aria-expanded="!inspectorCollapsed"
                :aria-label="t('Properties')"
                aria-controls="image-details"
                :title="t('Show or hide properties')"
                @click="inspectorCollapsed = !inspectorCollapsed"
              >
                <Icon name="sidebar" />
              </button>
            </div>
          </div>
          <form
            v-if="store.tool === 'text'"
            class="text-prompt-popover"
            :aria-label="t('Text prompt')"
            @submit.prevent="submitTextPrompt"
            @keydown.ctrl.enter.prevent.stop="submitTextPrompt"
            @keydown.meta.enter.prevent.stop="submitTextPrompt"
            @keydown.esc.prevent.stop="store.activateSelection()"
          >
            <div class="text-prompt-heading">
              <strong>{{ t("Text prompt") }}</strong
              ><button
                type="button"
                :aria-label="t('Close text prompt')"
                :title="t('Close text prompt · Esc')"
                @click="store.activateSelection()"
              >
                <Icon name="close" />
              </button>
            </div>
            <div class="text-prompt-input">
              <textarea
                rows="5"
                ref="textPromptInput"
                v-model="promptText"
                :aria-label="t('Text prompt')"
                :placeholder="t('English target description…')"
              ></textarea>
              <div class="text-prompt-footer">
                <small>{{
                  t("Enter: new line · Ctrl+Enter or ⌘Enter: preview")
                }}</small
                ><button
                  type="submit"
                  :disabled="
                    !promptText.trim() || !store.current || store.navigating
                  "
                >
                  {{ t("Preview text segmentation") }}
                </button>
              </div>
            </div>
          </form>
          <AnnotationCanvas ref="canvas" />
          <div v-if="!store.current" class="empty">
            <h2>{{ t("Open an image dataset") }}</h2>
            <p>{{ t("Start with images or import existing YOLO boxes.") }}</p>
            <NButton type="primary" @click="openDialog = true">{{
              t("Open project")
            }}</NButton>
          </div>
          <div class="imagebar">
            {{ store.current?.path ?? t("No image selected")
            }}<span
              >{{ store.annotation?.width }} ×
              {{ store.annotation?.height }}</span
            >
          </div>
          <CandidateBar />
          <FilmStrip />
        </section>
        <div
          class="split"
          role="separator"
          :aria-label="t('Resize right panel')"
          aria-orientation="vertical"
          @pointerdown="resize($event, 'right')"
          @dblclick="right = 340"
        ></div>
        <aside
          id="image-details"
          class="right-panel"
          :class="{ 'is-open': inspectorOpen }"
          :aria-label="t('Image details')"
        >
          <button class="inspector-close" @click="inspectorOpen = false">
            {{ t("Close image details") }}
          </button>
          <WorkspaceInspector>
            <template #actions>
              <div
                class="image-annotation-actions"
                role="group"
                :aria-label="t('Image annotation actions')"
              >
                <button
                  class="danger"
                  :disabled="!store.canClearImageAnnotations"
                  :aria-label="t('Clear image annotations…')"
                  :title="t('Clear image annotations…')"
                  @click="clearAnnotationsOpen = true"
                >
                  <Icon name="trash" />{{ t("Clear labels…") }}
                </button>
                <button
                  :disabled="!store.canClearAllPrompts"
                  :aria-label="t('Clear all prompts')"
                  :title="
                    t(
                      'Clear all points and box prompts on this image; keep masks, detection boxes and locked objects',
                    )
                  "
                  @click="store.clearAllPrompts()"
                >
                  <Icon name="promptbox" />{{ t("Clear prompts") }}
                </button>
                <button
                  :disabled="
                    !store.annotation?.instances.some(
                      (o) =>
                        !o.locked && !o.box && (o.mask || o.polygons.length),
                    ) || store.navigating
                  "
                  :aria-label="t('Create missing boxes from masks')"
                  :title="t('Create missing boxes from masks')"
                  @click="store.boxesFromMasks()"
                >
                  <Icon name="box" />{{ t("Masks to boxes") }}
                </button>
              </div>
            </template>
            <template #image>
              <div v-if="store.annotation" class="section">
                <h3>{{ t("Image review") }}</h3>
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
                    {{ t(label) }}
                  </button>
                </div>
                <label
                  class="empty-confirmation"
                  :class="{
                    confirmed: store.annotation.explicit_empty[store.task],
                  }"
                >
                  <input
                    type="checkbox"
                    ref="emptyConfirmation"
                    :aria-label="t('Confirm no objects for this task')"
                    aria-describedby="empty-confirmation-description"
                    :checked="store.annotation.explicit_empty[store.task]"
                    @change="
                      store.setExplicitEmpty(
                        ($event.target as HTMLInputElement).checked,
                      )
                    "
                  />
                  <span
                    ><strong>{{
                      t("Confirm no objects for this task")
                    }}</strong>
                    <small id="empty-confirmation-description">{{
                      t(
                        "Check the image before confirming; approval stays separate.",
                      )
                    }}</small></span
                  >
                </label>
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
                  :placeholder="t('Image tags, comma separated')"
                  @change="tags(($event.target as HTMLInputElement).value)"
                /><textarea
                  v-model="store.annotation.notes"
                  :placeholder="t('Image notes…')"
                  @change="store.changed()"
                ></textarea>
              </div>
            </template>
          </WorkspaceInspector>
        </aside>
      </main>
      <footer>
        <span>{{ toolLabel(store.tool) }}</span
        ><span>{{ t("A / D or ← / →: previous / next image") }}</span
        ><span class="grow"></span
        ><span :class="{ warning: store.dirty }">{{
          store.saving
            ? t("Saving…")
            : store.dirty
              ? t("Unsaved changes")
              : t("Saved")
        }}</span>
      </footer>
      <NModal
        :show="approvalWarning"
        preset="card"
        role="alertdialog"
        :title="t('Cannot approve this image')"
        style="width: 480px; max-width: 92vw; max-height: 85vh; overflow: auto"
        @update:show="!$event && (store.error = '')"
        @after-leave="approvalClosed"
      >
        <p>{{ uiError(store.error) }}</p>
        <p class="muted">
          {{
            t(
              "If the image has no objects for this task, confirm this explicitly in Image properties. Nothing is approved automatically.",
            )
          }}
        </p>
        <template #footer
          ><div class="approval-actions">
            <button @click="openApprovalProperties">
              {{ t("Open image properties") }}
            </button>
            <button class="primary" @click="store.error = ''">
              {{ t("Continue annotating") }}
            </button>
          </div></template
        >
      </NModal>
      <ClearImageAnnotations v-model:show="clearAnnotationsOpen" />
      <ExportSetup v-model:show="exportOpen" @started="batchStarted" />
      <NModal
        v-model:show="openDialog"
        preset="card"
        :title="t('Open project')"
        style="width: 520px"
        ><p>
          {{
            t(
              "Enter a folder path on the backend machine. An images subfolder and data.yaml are optional.",
            )
          }}
        </p>
        <input
          v-model="path"
          :placeholder="t('/path/to/dataset')"
          @keydown.enter="openProject"
        />
        <div class="row" style="margin-top: 16px">
          <NButton type="primary" @click="openProject">{{ t("Open") }}</NButton>
        </div></NModal
      >
      <ModelSettings v-model:show="modelSettings" />
      <BatchSetup
        v-model:show="batchSettings"
        @started="batchStarted"
        @models="
          batchSettings = false;
          modelSettings = true;
        "
      />
      <TaskWindow
        v-model:show="jobsOpen"
        :jobs="jobs"
        :images="store.images"
        @cancel="jobAction($event)"
        @resume="jobAction($event, true)"
        @logs="
          jobsOpen = false;
          logsOpen = true;
        "
      />
      <NModal
        v-model:show="classesOpen"
        preset="card"
        :title="t('Project classes')"
        style="
          width: 560px;
          max-width: 92vw;
          max-height: 85vh;
          overflow: hidden;
        "
        content-style="overflow:auto;min-height:0"
        ><p>
          {{
            t(
              "Manage names and colors. Use the class palette to assign annotations.",
            )
          }}
        </p>
        <CategoryEditor
          v-for="c in store.meta?.classes"
          :key="c.id"
          :category="c"
          @saved="store.applyCategory"
          @error="store.error = $event"
        />
        <button @click="createClass">{{ t("Add class") }}</button
        ><button @click="reindex">
          {{ t("Reindex IDs…") }}
        </button></NModal
      >
      <NModal
        v-model:show="tagsOpen"
        preset="card"
        :title="t('Project tags')"
        style="
          width: 560px;
          max-width: 92vw;
          max-height: 85vh;
          overflow: hidden;
        "
        content-style="overflow:auto;min-height:0"
      >
        <section class="tag-group" aria-labelledby="builtin-states-heading">
          <div class="row">
            <h3 id="builtin-states-heading">
              {{ t("Built-in review states") }}
            </h3>
            <span class="readonly-label">{{ t("Read only") }}</span>
          </div>
          <p class="muted">
            {{
              t(
                "Review is tracked per task. Excluded applies to the whole image.",
              )
            }}
          </p>
          <ul class="builtin-states">
            <li v-for="state in reviewStates" :key="state.value">
              <i :style="{ background: state.color }" aria-hidden="true"></i>
              <div>
                <strong>{{ t(state.label) }}</strong>
                <p class="muted">{{ t(state.description) }}</p>
              </div>
            </li>
          </ul>
        </section>
        <section class="tag-group" aria-labelledby="custom-tags-heading">
          <h3 id="custom-tags-heading">{{ t("Custom image tags") }}</h3>
          <p v-if="!store.meta?.tags.length" class="muted">
            {{ t("No custom tags yet.") }}
          </p>
          <CategoryEditor
            v-for="c in store.meta?.tags"
            :key="c.id"
            :category="c"
            @saved="store.applyCategory"
            @error="store.error = $event"
          />
          <p class="muted">
            {{
              t(
                "New tags are registered when added to an image. Their names and colors are editable here.",
              )
            }}
          </p>
        </section></NModal
      >
      <NModal
        v-model:show="help"
        preset="card"
        :title="t('Keyboard shortcuts')"
        style="
          width: 720px;
          max-width: 92vw;
          max-height: 85vh;
          overflow: hidden;
        "
        content-style="overflow:auto;min-height:0"
        ><input
          v-model="keySearch"
          :placeholder="t('Search actions or keys…')"
        />
        <div
          v-for="[action, key] in shortcuts.filter((row) =>
            [t(row[0]), t(row[1]), ...row]
              .join(' ')
              .toLowerCase()
              .includes(keySearch.toLowerCase()),
          )"
          class="shortcut"
        >
          <span>{{ t(action) }}</span
          ><kbd>{{ t(key) }}</kbd>
        </div>
        <p>
          {{ t("Single-key shortcuts are disabled while typing.") }}
        </p></NModal
      >
      <ClassPicker />
      <FastTooltip /></div
  ></NConfigProvider>
</template>
