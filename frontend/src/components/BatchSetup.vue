<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { NModal } from "naive-ui";
import {
  request,
  type Operation,
  type ScopePreview,
  type ModelCheck,
} from "../api";
import { useProject } from "../stores/project";
const props = defineProps<{ show: boolean }>();
const emit = defineEmits<{
  "update:show": [boolean];
  started: [];
  models: [];
}>();
const store = useProject();
const operation = ref<Operation>("segmentation"),
  range = ref("all"),
  states = ref(["pending"]),
  writePolicy = ref<"fill_empty" | "append">("fill_empty"),
  recalculate = ref(false),
  deviceType = ref("auto"),
  devices = ref("auto"),
  workers = ref("auto");
const preview = ref<ScopePreview | null>(null),
  check = ref<ModelCheck | null>(null),
  busy = ref(""),
  error = ref("");
let generation = 0;
const payload = computed(() => ({
  ...store.parameters(operation.value),
  operation: operation.value,
  model:
    operation.value === "boxes_from_masks"
      ? ""
      : store.parameters(operation.value).model,
  device_type:
    operation.value === "boxes_from_masks" ? "cpu" : deviceType.value,
  devices: operation.value === "boxes_from_masks" ? "auto" : devices.value,
  num_workers: operation.value === "boxes_from_masks" ? "1" : workers.value,
  review_states: states.value,
  write_policy: writePolicy.value,
  recalculate_boxes: recalculate.value,
  image_ids:
    range.value === "filtered" ? store.filtered.map((i) => i.id) : null,
}));
watch(
  () => props.show,
  (show) => {
    generation++;
    busy.value = "";
    if (show) {
      operation.value = store.task;
      range.value = "all";
      states.value = ["pending"];
      recalculate.value = false;
      writePolicy.value = store.parameters(operation.value).write_policy;
      preview.value = null;
      check.value = null;
      error.value = "";
    }
  },
);
watch(
  () => JSON.stringify(payload.value),
  () => {
    generation++;
    preview.value = null;
    check.value = null;
    error.value = "";
    busy.value = "";
  },
);
async function inspect() {
  const token = ++generation,
    project = store.meta?.id;
  busy.value = "Checking scope…";
  error.value = "";
  try {
    const snapshot = JSON.parse(JSON.stringify(payload.value));
    const result = await request<ScopePreview>(
      "/jobs/preview",
      "POST",
      snapshot,
    );
    let compatibility: ModelCheck | null = null;
    if (operation.value === "detection") {
      compatibility = await request<ModelCheck>(
        "/models/check",
        "POST",
        snapshot,
      );
      if (
        !snapshot.allow_new_classes &&
        !compatibility.compatibility?.accepted_classes
      )
        throw new Error(
          "No classes are accepted. Enable new classes in Model settings or define compatible project classes.",
        );
    }
    if (token === generation && project === store.meta?.id) {
      preview.value = result;
      check.value = compatibility;
    }
  } catch (e) {
    if (token === generation) error.value = String(e);
  } finally {
    if (token === generation) busy.value = "";
  }
}
async function start() {
  if (!preview.value) return;
  const token = ++generation,
    project = store.meta?.id;
  busy.value = "Starting…";
  error.value = "";
  try {
    const snapshot = JSON.parse(JSON.stringify(payload.value));
    await store.save();
    await request("/jobs", "POST", snapshot);
    if (token === generation && project === store.meta?.id) {
      emit("update:show", false);
      emit("started");
    }
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
    title="Batch processing"
    style="width: 720px; max-width: 90vw; max-height: 80vh; overflow: auto"
  >
    <div class="batch-fields">
      <label
        >Operation<select v-model="operation" :disabled="!!busy">
          <option value="detection">Detect boxes</option>
          <option value="segmentation">Segment existing boxes</option>
          <option value="boxes_from_masks">Boxes from masks</option>
        </select></label
      ><label
        >Image range<select v-model="range" :disabled="!!busy">
          <option value="all">
            All project images ({{ store.images.length }})
          </option>
          <option value="filtered">
            Current search results ({{ store.filtered.length }})
          </option>
        </select></label
      >
    </div>
    <section>
      <h3>
        Review states ·
        {{ operation === "segmentation" ? "Segmentation" : "Detection" }}
      </h3>
      <div class="batch-states">
        <label
          v-for="state in [
            { value: 'pending', label: 'Not reviewed' },
            { value: 'uncertain', label: 'Needs review' },
            { value: 'ok', label: 'Approved' },
          ]"
          :key="state.value"
          ><input
            v-model="states"
            type="checkbox"
            :value="state.value"
            :disabled="!!busy"
          />{{ state.label }}</label
        >
      </div>
      <p class="muted">
        Excluded images are always skipped. Selecting Approved does not permit
        overwriting existing manual annotations.
      </p>
    </section>
    <section v-if="operation !== 'boxes_from_masks'">
      <div class="row">
        <h3>Model · {{ payload.model || "Not configured" }}</h3>
        <button :disabled="!!busy" @click="emit('models')">
          Model settings
        </button>
      </div>
      <p v-if="operation === 'detection'" class="muted">
        Confidence {{ payload.confidence }} · NMS IoU {{ payload.iou }} ·
        {{
          payload.allow_new_classes
            ? "Add extra classes when detected"
            : "Discard classes outside the project"
        }}
      </p>
      <div class="batch-fields">
        <label
          >Device type<select v-model="deviceType" :disabled="!!busy">
            <option
              v-for="device in ['auto', 'cuda', 'cpu', 'mps']"
              :key="device"
            >
              {{ device }}
            </option>
          </select></label
        ><label
          >Logical CUDA devices<input
            v-model="devices"
            :disabled="!!busy"
            placeholder="auto or 0,1" /></label
        ><label
          >Workers<input
            v-model="workers"
            :disabled="!!busy"
            placeholder="auto or positive integer"
        /></label>
      </div>
      <p class="muted">
        Each worker holds a model copy. Additional workers on the same device
        require more memory.
      </p>
    </section>
    <section v-if="operation === 'detection'">
      <label
        >Write policy<select v-model="writePolicy" :disabled="!!busy">
          <option value="fill_empty">Empty images only</option>
          <option value="append">Append with duplicate checks</option>
        </select></label
      >
    </section>
    <section v-if="operation === 'boxes_from_masks'">
      <label
        ><input v-model="recalculate" type="checkbox" :disabled="!!busy" />
        Recalculate existing unlocked boxes</label
      >
      <p class="muted">
        Default: create missing boxes only. CPU geometry; no model or GPU. Masks
        and instance classes are preserved.
      </p>
    </section>
    <section v-if="preview" class="batch-preview">
      <h3>Scope preview</h3>
      <dl>
        <dt>Input images</dt>
        <dd>{{ preview.input_total }}</dd>
        <dt>Excluded</dt>
        <dd>{{ preview.counts.excluded }}</dd>
        <dt>Outside selected review states</dt>
        <dd>{{ preview.counts.review_state }}</dd>
        <dt>No eligible objects / existing labels</dt>
        <dd>{{ preview.counts.no_content }}</dd>
        <dt>Invalid inputs</dt>
        <dd>{{ preview.counts.invalid }}</dd>
        <dt>Images to process</dt>
        <dd>
          <strong>{{ preview.total }}</strong>
        </dd>
      </dl>
      <p v-if="check?.compatibility">
        Classes compatible ·
        {{ check.compatibility.extra_classes.length }} extra model classes
      </p>
      <p v-for="item in preview.errors" :key="item.image">
        {{ item.image }}: {{ item.error }}
      </p>
      <p v-if="!preview.total">
        No images require processing with these settings.
      </p>
    </section>
    <p v-if="busy" role="status">{{ busy }}</p>
    <p v-if="error" role="alert">{{ error }}</p>
    <div class="batch-actions">
      <button @click="emit('update:show', false)">Cancel</button
      ><button
        :disabled="
          !!busy ||
          !states.length ||
          (operation !== 'boxes_from_masks' && !payload.model)
        "
        @click="inspect"
      >
        Preview scope</button
      ><button
        class="primary"
        :disabled="!!busy || !preview?.total"
        @click="start"
      >
        Start
      </button>
    </div>
  </NModal>
</template>
<style scoped>
.batch-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px 24px;
}
.batch-fields label,
section > label {
  display: grid;
  gap: 7px;
  font-size: 12px;
}
.batch-states {
  display: flex;
  gap: 20px;
  flex-wrap: wrap;
}
.batch-states label {
  display: flex;
  gap: 6px;
  align-items: center;
}
section {
  margin-top: 22px;
  border-top: 1px solid var(--line);
  padding-top: 18px;
}
.batch-preview dl {
  display: grid;
  grid-template-columns: 1fr 80px;
  gap: 8px;
}
.batch-preview dd {
  text-align: right;
  margin: 0;
  font-variant-numeric: tabular-nums;
}
.batch-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 24px;
}
@media (max-width: 600px) {
  .batch-fields {
    grid-template-columns: 1fr;
  }
}
</style>
