<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { NModal } from "naive-ui";
import { request, type ExportPreview } from "../api";
import { t, uiError } from "../i18n";
import { useProject } from "../stores/project";
import { reviewStates } from "../review";
const props = defineProps<{ show: boolean }>();
const emit = defineEmits<{ "update:show": [boolean]; started: [] }>();
const store = useProject();
const task = ref<"detection" | "segmentation">("segmentation"),
  format = ref("yolo"),
  includePending = ref(false),
  output = ref(""),
  busy = ref(false),
  error = ref(""),
  preview = ref<ExportPreview | null>(null);
const payload = computed(() => ({
  task: task.value,
  format: format.value,
  include_pending: includePending.value,
  output: output.value.trim() || null,
}));
let generation = 0;
let previewTimer: ReturnType<typeof setTimeout> | undefined;
onBeforeUnmount(() => {
  generation++;
  clearTimeout(previewTimer);
});
watch(
  () => props.show,
  (show) => {
    generation++;
    busy.value = false;
    error.value = "";
    preview.value = null;
    if (show) {
      task.value = store.task;
      format.value = "yolo";
      includePending.value = false;
      output.value = "";
    }
  },
);
// Opening or changing export options refreshes the summary. Confirmation is a
// separate click and is invalidated by every scope or destination change.
watch(
  [
    () => props.show,
    () => task.value,
    () => format.value,
    () => includePending.value,
    () => output.value,
    () => store.meta?.id,
    () => store.meta?.session,
  ],
  (values, previous) => {
    generation++;
    clearTimeout(previewTimer);
    preview.value = null;
    error.value = "";
    busy.value = false;
    if (!props.show) return;
    if (previous?.[0] && values[4] !== previous[4]) {
      busy.value = true;
      previewTimer = setTimeout(() => void inspect(), 350);
    } else void inspect();
  },
  { immediate: true },
);
function context() {
  const token = ++generation,
    session = store.meta?.session,
    project = store.meta?.id;
  return () =>
    props.show &&
    generation === token &&
    store.meta?.id === project &&
    store.meta?.session === session;
}
async function inspect() {
  if (!props.show || !store.meta) return;
  const current = context(),
    snapshot = { ...payload.value };
  busy.value = true;
  error.value = "";
  try {
    await store.save();
    if (!current()) return;
    const result = await request<ExportPreview>(
      "/export/preview",
      "POST",
      snapshot,
    );
    if (current()) preview.value = result;
  } catch (e) {
    if (current()) error.value = String(e);
  } finally {
    if (current()) busy.value = false;
  }
}
async function start() {
  if (
    busy.value ||
    !props.show ||
    !store.meta ||
    !preview.value?.eligible ||
    preview.value.already_exported ||
    preview.value.errors.length
  )
    return;
  const current = context(),
    snapshot = {
      ...payload.value,
      output: preview.value.output,
      expected_signature: preview.value.signature,
    };
  busy.value = true;
  error.value = "";
  try {
    await store.save();
    if (!current()) return;
    await request("/export/jobs", "POST", snapshot);
    if (current()) {
      emit("update:show", false);
      emit("started");
    }
  } catch (e) {
    if (current()) {
      error.value = String(e);
      preview.value = null;
    }
  } finally {
    if (current()) busy.value = false;
  }
}
const reasons = [
  ["excluded", "Excluded"],
  ["uncertain", "Needs review"],
  ["pending", "Not reviewed"],
  ["unassigned", "Unassigned classes"],
  ["no_annotations", "No valid annotations"],
  ["invalid", "Invalid inputs"],
];
</script>
<template>
  <NModal
    :show="show"
    preset="card"
    :title="t('Export dataset')"
    style="width: 640px; max-width: 92vw; max-height: 85vh; overflow: hidden"
    content-style="overflow: auto; min-height: 0"
    @update:show="emit('update:show', $event)"
  >
    <div class="export-fields">
      <label
        >{{ t("Task")
        }}<select v-model="task" :disabled="busy">
          <option value="detection">{{ t("Detection") }}</option>
          <option value="segmentation">{{ t("Segmentation") }}</option>
        </select></label
      >
      <label
        >{{ t("Format")
        }}<select v-model="format" :disabled="busy">
          <option value="yolo">YOLO</option>
          <option value="coco">COCO</option>
        </select></label
      >
    </div>
    <p>
      {{
        t(
          "Approved images are exported by default. Excluded and Needs review images are always skipped.",
        )
      }}
    </p>
    <label class="export-pending"
      ><input type="checkbox" v-model="includePending" :disabled="busy" />{{
        t("Include Not reviewed annotations")
      }}</label
    >
    <label class="export-destination"
      >{{ t("Output folder on the backend") }}
      <input
        v-model="output"
        :disabled="busy && !!preview"
        :placeholder="t('Leave empty for the project export folder')"
      />
    </label>
    <p class="muted">
      {{
        t(
          "Use a new folder. Absolute paths are supported; relative paths use the project root. Existing datasets are never overwritten. The browser does not download files.",
        )
      }}
    </p>
    <p v-if="busy" role="status">{{ t("Checking export…") }}</p>
    <section
      v-if="preview && !busy"
      class="export-summary"
      :aria-label="t('Export summary')"
    >
      <h3>{{ t("Export summary") }}</h3>
      <dl>
        <dt>{{ t("Total images") }}</dt>
        <dd>{{ preview.total }}</dd>
        <template v-for="state in reviewStates" :key="state.value">
          <dt class="review-depth-one">{{ t(state.label) }}</dt>
          <dd>{{ preview.counts[state.value] || 0 }}</dd>
          <template v-if="preview.no_valid_annotations?.[state.value]">
            <dt
              class="review-subset"
              :title="
                t('No valid labels for this task, and not confirmed empty.')
              "
            >
              {{ t("No valid annotations") }}
            </dt>
            <dd class="review-subset-count">
              {{ preview.no_valid_annotations[state.value] }}
            </dd>
          </template>
        </template>
      </dl>
      <dl class="export-eligibility">
        <dt>
          <strong>{{ t("Images to export") }}</strong>
        </dt>
        <dd>
          <strong>{{ preview.eligible }}</strong>
        </dd>
      </dl>
      <details :open="preview.total > preview.eligible">
        <summary>
          {{
            t("Skipped images ({count})", {
              count: preview.total - preview.eligible,
            })
          }}
        </summary>
        <dl>
          <template v-for="state in reviewStates" :key="state.value">
            <dt class="review-depth-one">{{ t(state.label) }}</dt>
            <dd>{{ preview.skipped_by_state?.[state.value] || 0 }}</dd>
            <template
              v-if="preview.skipped_no_valid_annotations?.[state.value]"
            >
              <dt
                class="review-subset"
                :title="
                  t('No valid labels for this task, and not confirmed empty.')
                "
              >
                {{ t("No valid annotations") }}
              </dt>
              <dd class="review-subset-count">
                {{ preview.skipped_no_valid_annotations[state.value] }}
              </dd>
            </template>
          </template>
          <template v-if="preview.skipped_by_state?.unknown">
            <dt>{{ t("Unknown review state") }}</dt>
            <dd>{{ preview.skipped_by_state.unknown }}</dd>
          </template>
        </dl>
        <div
          v-if="preview.skipped_images?.length || preview.errors.length"
          class="export-file-details"
          role="region"
          tabindex="0"
          :aria-label="t('Skipped image details')"
        >
          <ul v-if="preview.skipped_images?.length" class="export-skipped-list">
            <li v-for="item in preview.skipped_images" :key="item.image">
              <span>{{ item.image }}</span> —
              {{
                t(
                  reasons.find(([key]) => key === item.reason)?.[1] ||
                    item.reason,
                )
              }}
            </li>
          </ul>
          <p v-for="item in preview.errors" :key="item.image">
            {{ item.image }}: {{ item.error }}
          </p>
        </div>
        <p
          v-if="
            (preview.skipped_images?.length || 0) <
            preview.total - preview.eligible
          "
          class="muted"
        >
          {{
            t("Showing {shown} of {total} skipped images.", {
              shown: preview.skipped_images?.length || 0,
              total: preview.total - preview.eligible,
            })
          }}
        </p>
      </details>
      <p v-if="!preview.eligible" role="status">
        {{
          t(
            "No images qualify. Approve annotations or include Not reviewed annotations, then check the summary again.",
          )
        }}
      </p>
      <p v-if="preview.already_exported" class="export-existing" role="status">
        {{
          t(
            "Already exported. The dataset is unchanged and the previous export is intact.",
          )
        }}
      </p>
      <p class="export-output">{{ preview.output }}</p>
    </section>
    <p v-if="error" role="alert">{{ uiError(error) }}</p>
    <template #footer>
      <div class="export-actions">
        <button @click="emit('update:show', false)">{{ t("Cancel") }}</button>
        <button :disabled="busy" @click="inspect">
          {{ t("Refresh summary") }}
        </button>
        <button
          class="primary"
          :disabled="
            busy ||
            !preview?.eligible ||
            preview.already_exported ||
            !!preview.errors.length
          "
          @click="start"
        >
          {{ t("Confirm export") }}
        </button>
      </div>
    </template>
  </NModal>
</template>
<style scoped>
.export-fields {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}
.export-fields label,
.export-destination {
  display: grid;
  gap: 7px;
  min-width: 0;
}
.export-destination {
  margin-top: 16px;
}
.export-pending {
  display: flex;
  align-items: center;
  gap: 8px;
}
p {
  line-height: 1.6;
}
.export-summary {
  margin-top: 18px;
  border-top: 1px solid var(--line);
  padding-top: 10px;
}
.export-summary dl {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 8px;
}
.export-summary dd {
  margin: 0;
  font-variant-numeric: tabular-nums;
}
.export-output {
  overflow-wrap: anywhere;
  color: #576578;
}
.export-existing {
  color: #187044;
}
.export-actions {
  display: flex;
  justify-content: flex-end;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 0;
}
.review-depth-one {
  padding-inline-start: 18px;
}
.review-subset {
  padding-inline-start: 36px;
  color: #985d18;
}
.review-subset-count {
  color: #985d18;
}
.export-eligibility {
  border-top: 1px solid var(--line);
  padding-top: 12px;
}

.export-file-details {
  max-height: min(240px, 30vh);
  overflow: auto;
  overscroll-behavior: contain;
  scrollbar-gutter: stable;
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 10px 12px;
  margin: 12px 0;
  overflow-wrap: anywhere;
}
.export-file-details:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
.export-file-details > p {
  margin: 8px 0;
}
.export-skipped-list {
  margin: 0;
  padding-inline-start: 20px;
  overflow-wrap: anywhere;
  line-height: 1.6;
}
.export-skipped-list li + li {
  margin-top: 6px;
}
</style>
