<script setup lang="ts">
import BoxPaddingControls from "./BoxPaddingControls.vue";
import { t, uiError } from "../i18n";
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
// Every action uses a frozen configuration and project session. A late preflight
// must not start work after the window closes or the project changes.
async function run(startJob: boolean) {
  if (busy.value || !props.show || !store.meta || !states.value.length) return;
  const token = ++generation,
    project = store.meta.id,
    session = store.meta.session,
    snapshot = JSON.parse(JSON.stringify(payload.value));
  const current = () =>
    token === generation &&
    props.show &&
    project === store.meta?.id &&
    session === store.meta?.session;
  busy.value = "Checking scope…";
  error.value = "";
  try {
    if (startJob) {
      await store.save();
      if (!current()) return;
    }
    const result = await request<ScopePreview>(
      "/jobs/preview",
      "POST",
      snapshot,
    );
    if (!current()) return;
    preview.value = result;
    let compatibility: ModelCheck | null = null;
    if (snapshot.operation === "detection") {
      compatibility = await request<ModelCheck>(
        "/models/check",
        "POST",
        snapshot,
      );
      if (!current()) return;
      if (
        !snapshot.allow_new_classes &&
        !compatibility.compatibility?.accepted_classes
      )
        throw new Error(
          "No classes are accepted. Enable new classes in Model settings or define compatible project classes.",
        );
    }
    check.value = compatibility;
    if (!startJob || !result.total) return;
    busy.value = "Starting…";
    await request("/jobs", "POST", snapshot);
    if (current()) {
      emit("update:show", false);
      emit("started");
    }
  } catch (e) {
    if (current()) error.value = String(e);
  } finally {
    if (token === generation) busy.value = "";
  }
}
function inspect() {
  return run(false);
}
function start() {
  return run(true);
}
</script>
<template>
  <NModal
    :show="show"
    @update:show="emit('update:show', $event)"
    preset="card"
    :title="t('Batch processing')"
    style="width: 720px; max-width: 90vw; max-height: 80vh; overflow: auto"
  >
    <div class="batch-fields">
      <label
        >{{ t("Operation")
        }}<select v-model="operation" :disabled="!!busy">
          <option value="detection">{{ t("Detect boxes") }}</option>
          <option value="segmentation">
            {{ t("Segment existing boxes") }}
          </option>
          <option value="boxes_from_masks">{{ t("Boxes from masks") }}</option>
        </select></label
      ><label
        >{{ t("Image range")
        }}<select v-model="range" :disabled="!!busy">
          <option value="all">
            {{
              t("All project images ({count})", { count: store.images.length })
            }}
          </option>
          <option value="filtered">
            {{
              t("Current search results ({count})", {
                count: store.filtered.length,
              })
            }}
          </option>
        </select></label
      >
    </div>
    <section>
      <h3>
        {{ t("Review states ·") }}
        {{ operation === "segmentation" ? t("Segmentation") : t("Detection") }}
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
          />{{ t(state.label) }}</label
        >
      </div>
      <p class="muted">
        {{
          t(
            "Excluded images are always skipped. Selecting Approved does not permit overwriting existing manual annotations.",
          )
        }}
      </p>
    </section>
    <section v-if="operation !== 'boxes_from_masks'">
      <div class="row">
        <h3>{{ t("Model ·") }} {{ payload.model || t("Not configured") }}</h3>
        <button :disabled="!!busy" @click="emit('models')">
          {{ t("Model settings") }}
        </button>
      </div>
      <p v-if="operation === 'detection'" class="muted">
        {{ t("Confidence") }} {{ payload.confidence }} {{ t("· NMS IoU") }}
        {{ payload.iou }} ·
        {{
          payload.allow_new_classes
            ? t("Add extra classes when detected")
            : t("Discard classes outside the project")
        }}
      </p>
      <div class="batch-fields">
        <label
          >{{ t("Device type")
          }}<select v-model="deviceType" :disabled="!!busy">
            <option
              v-for="device in ['auto', 'cuda', 'cpu', 'mps']"
              :key="device"
            >
              {{ device }}
            </option>
          </select></label
        ><label
          >{{ t("Logical CUDA devices")
          }}<input
            v-model="devices"
            :disabled="!!busy"
            :placeholder="t('auto or 0,1')" /></label
        ><label
          >{{ t("Workers")
          }}<input
            v-model="workers"
            :disabled="!!busy"
            :placeholder="t('auto or positive integer')"
        /></label>
      </div>
      <p class="muted">
        {{
          t(
            "Each worker holds a model copy. Additional workers on the same device require more memory.",
          )
        }}
      </p>
    </section>
    <section v-if="operation === 'detection'">
      <label
        >{{ t("Write policy")
        }}<select v-model="writePolicy" :disabled="!!busy">
          <option value="fill_empty">{{ t("Empty images only") }}</option>
          <option value="append">
            {{ t("Append with duplicate checks") }}
          </option>
        </select></label
      >
    </section>
    <section v-if="operation === 'boxes_from_masks'">
      <BoxPaddingControls :disabled="!!busy" />
      <label
        ><input v-model="recalculate" type="checkbox" :disabled="!!busy" />
        {{ t("Recalculate existing unlocked boxes") }}</label
      >
      <p class="muted">
        {{
          t(
            "Default: create missing boxes only. CPU geometry; no model or GPU. Masks and instance classes are preserved.",
          )
        }}
      </p>
    </section>
    <section v-if="preview" class="batch-preview">
      <h3>{{ t("Scope preview") }}</h3>
      <dl>
        <dt>{{ t("Input images") }}</dt>
        <dd>{{ preview.input_total }}</dd>
        <dt>{{ t("Excluded") }}</dt>
        <dd>{{ preview.counts.excluded }}</dd>
        <dt>{{ t("Outside selected review states") }}</dt>
        <dd>{{ preview.counts.review_state }}</dd>
        <dt>{{ t("No eligible objects / existing labels") }}</dt>
        <dd>{{ preview.counts.no_content }}</dd>
        <dt>{{ t("Invalid inputs") }}</dt>
        <dd>{{ preview.counts.invalid }}</dd>
        <dt>{{ t("Images to process") }}</dt>
        <dd>
          <strong>{{ preview.total }}</strong>
        </dd>
      </dl>
      <p v-if="check?.compatibility">
        {{ t("Classes compatible ·") }}
        {{ check.compatibility.extra_classes.length }}
        {{ t("extra model classes") }}
      </p>
      <p v-for="item in preview.errors" :key="item.image">
        {{ item.image }}: {{ item.error }}
      </p>
      <p v-if="!preview.total">
        {{ t("No images require processing with these settings.") }}
      </p>
    </section>
    <p v-if="busy" role="status">{{ t(busy) }}</p>
    <p v-if="error" role="alert">{{ uiError(error) }}</p>
    <div class="batch-actions">
      <button @click="emit('update:show', false)">{{ t("Cancel") }}</button
      ><button
        :disabled="
          !!busy ||
          !states.length ||
          (operation !== 'boxes_from_masks' && !payload.model)
        "
        @click="inspect"
      >
        {{ t("Preview scope") }}</button
      ><button
        class="primary"
        :disabled="
          !!busy ||
          !states.length ||
          (operation !== 'boxes_from_masks' && !payload.model)
        "
        @click="start"
      >
        {{ t("Start") }}
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
