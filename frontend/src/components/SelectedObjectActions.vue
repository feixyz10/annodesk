<script setup lang="ts">
import { computed } from "vue";
import { NSelect } from "naive-ui";
import BoxPaddingControls from "./BoxPaddingControls.vue";
import { t, toolLabel } from "../i18n";
import { useProject } from "../stores/project";
const store = useProject();
const blocked = computed(() => !!(store.object?.locked || store.navigating));
const prompts = computed(
  () =>
    !!(
      store.object?.box ||
      store.object?.prompt_box ||
      store.object?.points.length
    ),
);
const options = computed(() =>
  (store.meta?.classes ?? []).map((c) => ({
    label: `${c.index} · ${c.name}`,
    value: c.id,
  })),
);
const deleteLabel = computed(() =>
  store.selectedPrompt === "box"
    ? "Delete box prompt"
    : typeof store.selectedPrompt === "number"
      ? "Delete point"
      : store.selectedGeometry === "box"
        ? "Delete box only"
        : store.selectedGeometry === "mask"
          ? "Delete mask only"
          : "Delete object",
);
function editCoordinate(event: Event, index: number) {
  const input = event.target as HTMLInputElement;
  const obj = store.object;
  if (!obj?.box) return;
  const box = [...obj.box];
  box[index] = input.valueAsNumber;
  store.editBox(obj.id, box);
  input.value = String(obj.box[index]);
}
</script>
<template>
  <section
    class="selection-actions"
    role="toolbar"
    :aria-label="t('Selected object actions')"
  >
    <template v-if="store.object">
      <div class="property-section">
        <label class="property-label"
          >{{ t("Class") }}
          <span v-if="store.object.confidence != null" class="muted"
            >{{ t("Confidence") }}
            {{ (store.object.confidence * 100).toFixed(1) }}%</span
          ><kbd>C</kbd></label
        >
        <NSelect
          :value="store.object.class_id"
          :options="options"
          filterable
          :disabled="blocked"
          :placeholder="t('Search by class name or ID…')"
          :aria-label="t('Change class')"
          @update:value="store.assign($event)"
        />
      </div>
      <div v-if="store.task === 'segmentation'" class="property-section">
        <div class="property-button-row">
          <button
            class="primary"
            :disabled="
              blocked ||
              store.object.hidden ||
              store.annotation?.excluded ||
              !prompts
            "
            :title="
              t(
                'Update the selected mask from its current points or box · Enter',
              )
            "
            @click="store.segment()"
          >
            {{ t("Refine mask") }}</button
          ><button
            :disabled="!store.canGenerateCandidates || !!store.candidates"
            :title="
              t(
                'Preview alternative masks for the selected instance; batch processing always uses one mask',
              )
            "
            data-candidate-trigger
            @click="store.generateCandidates()"
          >
            {{ t("Generate candidates") }}
          </button>
        </div>
        <button
          v-if="store.object.points.length || store.object.prompt_box"
          :disabled="blocked"
          :title="
            t(
              'Remove all points and the box prompt; keep the mask and detection box',
            )
          "
          @click="store.deletePrompt(true)"
        >
          {{ t("Clear prompts") }}
        </button>
      </div>
      <details
        v-if="store.object.prompt_box || store.object.points.length"
        class="property-section prompt-details"
        :open="store.selectedPrompt !== null"
      >
        <summary>{{ t("Prompt details") }}</summary>
        <div class="property-button-row">
          <button
            v-if="store.object.prompt_box"
            class="prompt-geometry"
            :aria-pressed="store.selectedPrompt === 'box'"
            @click="store.selectPrompt(store.object.id, 'box')"
          >
            {{ t("SAM box prompt") }}</button
          ><button
            v-if="store.object.points.length"
            class="prompt-geometry"
            :aria-pressed="typeof store.selectedPrompt === 'number'"
            @click="store.selectPrompt(store.object.id, 0)"
          >
            {{ t("Points: {count}", { count: store.object.points.length }) }}
          </button>
        </div>
        <div class="prompt-point-list">
          <button
            v-for="(point, index) in store.object.points"
            :key="index"
            :aria-pressed="store.selectedPrompt === index"
            @click="store.selectPrompt(store.object.id, index)"
          >
            <span
              >{{ t(point.positive ? "Positive point" : "Negative point") }}
              {{ index + 1 }}</span
            ><small>{{ Math.round(point.x) }}, {{ Math.round(point.y) }}</small>
          </button>
        </div>
        <button
          :disabled="blocked || store.selectedPrompt === null"
          @click="store.deletePrompt()"
        >
          {{ t("Delete prompt") }}
        </button>
      </details>
      <div
        v-if="
          store.object.box || store.object.mask || store.object.polygons.length
        "
        class="property-section"
      >
        <strong>{{ t("Detection box") }}</strong>
        <details v-if="store.object.box" class="box-coordinate-settings">
          <summary>{{ t("Box coordinates") }}</summary>
          <div v-if="store.object.box" class="coords">
            <label v-for="(_, i) in store.object.box" :key="i"
              >{{ ["x1", "y1", "x2", "y2"][i]
              }}<input
                type="number"
                :disabled="blocked"
                :value="store.object.box[i]"
                @change="editCoordinate($event, i)"
            /></label>
          </div>
        </details>
        <template v-if="store.object.mask || store.object.polygons.length"
          ><button
            :disabled="blocked"
            @click="store.boxesFromMasks(true, !!store.object.box)"
          >
            {{
              store.object.box
                ? t("Recalculate box from mask")
                : t("Create box from mask")
            }}
          </button>
          <details class="box-padding-settings">
            <summary>{{ t("Mask to box padding") }}</summary>
            <BoxPaddingControls :disabled="blocked" /></details
        ></template>
      </div>
      <div class="property-section property-danger">
        <button
          v-if="deleteLabel !== 'Delete object'"
          class="selection-delete"
          :disabled="blocked"
          :title="t('Delete only the current selection · X or Delete')"
          @click="store.deleteSelected()"
        >
          {{ t(deleteLabel) }}</button
        ><button
          class="selection-delete-whole"
          :disabled="blocked"
          :title="
            t(
              'Delete the mask, detection box and all prompts · Shift+X or Shift+Delete',
            )
          "
          @click="store.remove()"
        >
          {{ t("Delete object") }}
        </button>
      </div>
    </template>
    <div v-else class="property-section inspector-empty">
      <strong>{{ t("Object tools") }}</strong>
      <p class="muted">
        {{
          t(
            "Select an object to edit its class, geometry and prompts, or start a new object.",
          )
        }}
      </p>
      <dl>
        <dt>{{ t("Class") }}</dt>
        <dd>
          {{
            store.meta?.classes.find((c) => c.id === store.defaultClass)
              ?.name ?? t("Unassigned")
          }}
        </dd>
        <dt>{{ t("Tool") }}</dt>
        <dd>{{ toolLabel(store.tool) }}</dd>
      </dl>
      <button
        :disabled="!store.current || store.navigating"
        @click="store.newObject()"
      >
        {{ t("New object") }} <kbd>N</kbd>
      </button>
    </div>
    <div
      v-if="store.promptStatus"
      class="selection-feedback"
      role="status"
      aria-live="polite"
    >
      {{ t(store.promptStatus) }}
    </div>
  </section>
</template>
