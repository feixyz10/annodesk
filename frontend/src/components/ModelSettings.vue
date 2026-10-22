<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { NModal } from "naive-ui";
import { request, type ModelCheck, type ModelParameters } from "../api";
import { useProject } from "../stores/project";
const props = defineProps<{ show: boolean }>();
const emit = defineEmits<{ "update:show": [boolean] }>();
const store = useProject();
const mode = ref<"detection" | "segmentation">("segmentation");
const draft = ref<ModelParameters>(store.parameters("segmentation"));
const check = ref<ModelCheck | null>(null),
  busy = ref(""),
  error = ref(""),
  selectedClasses = ref("");
let generation = 0;
const options = computed(
  () =>
    store.models?.models.filter(
      (m) => (m.task || "segmentation") === mode.value,
    ) || [],
);
const chosen = computed(() =>
  options.value.find((m) => m.id === draft.value.model),
);
const state = computed(() =>
  !chosen.value?.available
    ? "Unavailable"
    : store.models?.loaded_model === draft.value.model
      ? "Loaded"
      : "Available · not loaded",
);
function selectModel() {
  generation++;
  check.value = null;
  error.value = "";
  draft.value = store.parameters(mode.value, draft.value.model);
  selectedClasses.value = draft.value.model_classes?.join(", ") || "";
}
function changeMode() {
  draft.value = store.parameters(mode.value);
  if (!options.value.some((m) => m.id === draft.value.model))
    draft.value.model = options.value[0]?.id || "";
  selectModel();
}
watch(
  () => props.show,
  async (show) => {
    const token = ++generation;
    busy.value = "";
    if (!show) return;
    mode.value = store.task;
    await store.refreshModels();
    if (props.show && generation === token) changeMode();
  },
);
function parameters() {
  const pieces = selectedClasses.value.trim();
  const ids = pieces ? pieces.split(",").map((v) => Number(v.trim())) : null;
  if (
    ids &&
    (pieces.split(",").some((v) => !v.trim()) ||
      ids.some((i) => !Number.isInteger(i) || i < 0) ||
      new Set(ids).size !== ids.length)
  )
    throw new Error(
      "Class filter must contain distinct nonnegative IDs, separated by commas.",
    );
  return { ...draft.value, operation: mode.value, model_classes: ids };
}
async function inspect(load = false) {
  const token = ++generation,
    project = store.meta?.id;
  busy.value = load ? "Loading model…" : "Checking model classes…";
  error.value = "";
  try {
    const result = await request<ModelCheck>(
      load ? "/models/load" : "/models/check",
      "POST",
      parameters(),
    );
    if (token !== generation || !props.show || store.meta?.id !== project)
      return;
    check.value = result;
    await store.refreshModels();
  } catch (e) {
    if (token === generation) error.value = String(e);
  } finally {
    if (token === generation) busy.value = "";
  }
}
async function apply() {
  const token = ++generation,
    project = store.meta?.id;
  busy.value = "Applying settings…";
  error.value = "";
  try {
    await store.applyModel(parameters());
    if (token === generation && store.meta?.id === project)
      emit("update:show", false);
  } catch (e) {
    if (token === generation) error.value = String(e);
  } finally {
    if (token === generation) busy.value = "";
  }
}
</script>
<template>
  <NModal
    :show="show"
    @update:show="emit('update:show', $event)"
    preset="card"
    title="Model settings"
    style="width: 900px; max-width: 90vw; max-height: 80vh; overflow: auto"
  >
    <div class="model-tabs" role="tablist" aria-label="Model task">
      <button
        v-for="task in ['detection', 'segmentation'] as const"
        :key="task"
        role="tab"
        :aria-selected="mode === task"
        :class="{ active: mode === task }"
        :disabled="!!busy"
        @click="
          mode = task;
          changeMode();
        "
      >
        {{ task === "detection" ? "Detection" : "Segmentation" }}
      </button>
    </div>
    <p class="muted">
      Settings apply to this project. Model weights stay on the backend; no
      automatic downloads.
    </p>
    <div class="model-form">
      <label
        >Model<select
          v-model="draft.model"
          :disabled="!!busy"
          @change="selectModel"
        >
          <option v-for="model in options" :key="model.id" :value="model.id">
            {{ model.name }}{{ model.available ? "" : " (unavailable)" }}
          </option>
        </select></label
      >
      <div class="model-state">
        <strong>{{ state }}</strong
        ><span v-if="store.models?.loaded_model === draft.model">{{
          store.models?.loaded_device
        }}</span>
      </div>
    </div>
    <p v-if="!options.length">
      No {{ mode }} models configured. Add a compatible local model to
      models.json, then Reload.
    </p>
    <div class="model-actions">
      <button :disabled="!!busy" @click="store.refreshModels()">
        Reload configuration</button
      ><button :disabled="!!busy || !chosen?.available" @click="inspect(false)">
        Check {{ mode === "detection" ? "classes" : "availability" }}</button
      ><button :disabled="!!busy || !chosen?.available" @click="inspect(true)">
        Load model
      </button>
    </div>
    <section class="model-section">
      <h3>Execution device</h3>
      <div class="model-fields">
        <label
          >Device type<select v-model="draft.device_type" :disabled="!!busy">
            <option
              v-for="device in ['auto', 'cuda', 'cpu', 'mps']"
              :key="device"
            >
              {{ device }}
            </option>
          </select></label
        ><label
          >Logical CUDA devices<input
            v-model="draft.devices"
            :disabled="!!busy"
            placeholder="auto or 0,1"
        /></label>
      </div>
      <p class="muted">
        Load uses one device. Batch jobs configure their own device and worker
        plan.
      </p>
    </section>
    <template v-if="mode === 'detection'">
      <section class="model-section">
        <h3>Detection parameters</h3>
        <div class="model-fields">
          <label
            >Confidence threshold<input
              v-model.number="draft.confidence"
              type="number"
              min="0"
              max="1"
              step="0.05"
              :disabled="!!busy" /></label
          ><label
            >NMS IoU<input
              v-model.number="draft.iou"
              type="number"
              min="0"
              max="1"
              step="0.05"
              :disabled="!!busy" /></label
          ><label
            >Input size<input
              v-model.number="draft.imgsz"
              type="number"
              min="32"
              max="8192"
              step="32"
              :disabled="!!busy" /></label
          ><label
            >Maximum detections<input
              v-model.number="draft.max_det"
              type="number"
              min="1"
              max="10000"
              :disabled="!!busy" /></label
          ><label
            >Model class filter<input
              v-model="selectedClasses"
              placeholder="All classes, or 0,2,5"
              :disabled="!!busy" /></label
          ><label
            >Write policy<select
              v-model="draft.write_policy"
              :disabled="!!busy"
            >
              <option value="fill_empty">Empty images only</option>
              <option value="append">
                Append; preserve existing annotations
              </option>
            </select></label
          >
        </div>
      </section>
      <section class="model-section">
        <h3>Project class compatibility</h3>
        <p>
          IDs and names must match exactly, or one complete class table must be
          a subset of the other.
        </p>
        <label class="new-class-toggle"
          ><input
            v-model="draft.allow_new_classes"
            type="checkbox"
            :disabled="!!busy"
          />
          Allow new classes from this model</label
        >
        <p class="muted">
          When enabled, extra classes are added only when a retained detection
          is saved. Original IDs are preserved.
        </p>
        <template v-if="check?.compatibility"
          ><p class="compatible">
            Compatible ·
            {{ check.compatibility.relation.replaceAll("_", " ") }} ·
            {{ check.compatibility.accepted_classes }} existing classes
          </p>
          <div class="model-class-table">
            <div v-for="(name, id) in check.class_names" :key="id">
              <span>{{ id }}</span
              ><strong>{{ name }}</strong
              ><span>{{
                store.meta?.classes.some((c) => c.index === Number(id))
                  ? "Existing"
                  : draft.allow_new_classes
                    ? "Add when detected"
                    : "Discard results"
              }}</span>
            </div>
          </div></template
        >
      </section>
    </template>
    <p v-if="busy" role="status">{{ busy }}</p>
    <div v-if="error" role="alert" class="model-error">
      <p>
        Settings could not be checked or applied. Review the diagnostics below.
      </p>
      <details open>
        <summary>Diagnostics</summary>
        <pre>{{ error }}</pre>
      </details>
    </div>
    <div class="model-footer">
      <span class="muted"
        >Load is a runtime action. Apply saves settings; Cancel discards
        unapplied changes.</span
      ><button @click="emit('update:show', false)">Cancel</button
      ><button class="primary" :disabled="!!busy || !chosen" @click="apply">
        Apply
      </button>
    </div>
  </NModal>
</template>
<style scoped>
.model-tabs,
.model-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.model-tabs button {
  min-width: 130px;
}
.model-form {
  display: grid;
  grid-template-columns: minmax(220px, 1fr) 200px;
  gap: 20px;
  align-items: end;
}
.model-form label,
.model-fields label {
  display: grid;
  gap: 7px;
  font-size: 12px;
}
.model-state {
  display: grid;
  gap: 6px;
  padding: 7px 0;
}
.model-actions {
  margin: 16px 0;
}
.model-section {
  margin-top: 22px;
  padding-top: 18px;
  border-top: 1px solid var(--line);
}
.model-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px 24px;
}
.model-class-table {
  max-height: 230px;
  overflow: auto;
}
.model-class-table > div {
  display: grid;
  grid-template-columns: 40px 1fr 150px;
  gap: 12px;
  padding: 8px;
  border-bottom: 1px solid var(--line);
  font-size: 12px;
}
.compatible {
  color: #24835d;
}
.model-footer {
  display: flex;
  gap: 10px;
  align-items: center;
  justify-content: flex-end;
  margin-top: 24px;
  border-top: 1px solid var(--line);
  padding-top: 18px;
}
.model-footer span {
  margin-right: auto;
  max-width: 460px;
}
.model-error {
  background: #fff4f5;
  padding: 12px;
  border-radius: 8px;
}
.model-error pre {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font-size: 12px;
}
.new-class-toggle {
  display: flex;
  gap: 8px;
  align-items: center;
}
@media (max-width: 650px) {
  .model-fields,
  .model-form {
    grid-template-columns: 1fr;
  }
  .model-footer {
    flex-wrap: wrap;
  }
}
</style>
