<script setup lang="ts">
import { computed } from "vue";
import { useProject } from "../stores/project";
import { t, toolLabel, uiError } from "../i18n";
const store = useProject();
defineEmits<{ finish: []; cancel: [] }>();
const size = computed({
  get: () => (store.tool === "eraser" ? store.eraserSize : store.brushSize),
  set: (value: number) => {
    const n = Math.max(1, Math.min(512, Math.round(Number(value) || 1)));
    if (store.tool === "eraser") store.eraserSize = n;
    else store.brushSize = n;
  },
});
const objectNumber = computed(
  () =>
    (store.annotation?.instances.findIndex((o) => o.id === store.selected) ??
      -1) + 1,
);
function sizeChanged(e: Event) {
  size.value = (e.target as HTMLInputElement).valueAsNumber;
}
</script>
<template>
  <div
    class="manual-mask-controls"
    role="toolbar"
    :aria-label="t('Manual mask tools')"
  >
    <template v-if="store.candidates?.protected">
      <strong
        :title="
          t('SAM replaces the current mask only after you apply the preview.')
        "
        >{{ t("Preview replacement") }}</strong
      >
      <span v-if="store.candidates.phase === 'loading'" role="status">{{
        t("Generating…")
      }}</span>
      <span
        v-if="store.candidates.phase === 'error'"
        class="warning"
        :title="uiError(store.candidates.error)"
        >{{ t("Preview failed") }}</span
      >
      <button
        v-if="store.candidates.phase === 'error'"
        @click="store.generateCandidates(true)"
      >
        {{ t("Retry") }}
      </button>
      <template v-if="(store.candidates.response?.items.length ?? 0) > 1">
        <button
          v-for="(item, i) in store.candidates.response?.items"
          :key="i"
          :aria-label="t('Candidate {number}', { number: i + 1 })"
          :aria-pressed="store.candidates.active === i"
          :class="{ active: store.candidates.active === i }"
          :title="
            t('Candidate {number} · predicted quality, not accuracy', {
              number: i + 1,
            }) + (item.quality == null ? '' : ` · ${item.quality.toFixed(3)}`)
          "
          :disabled="store.candidates.phase === 'applying'"
          @click="store.candidates.active = i"
        >
          {{ i + 1 }}
        </button>
      </template>
      <button
        class="primary"
        :disabled="
          store.candidates.phase !== 'ready' ||
          !store.object ||
          !store.layerVisible(store.object, 'mask')
        "
        @click="store.applyCandidate()"
      >
        {{ t("Apply replacement") }}
      </button>
      <button
        :disabled="store.candidates.phase === 'applying'"
        @click="store.cancelCandidates()"
      >
        {{ t("Cancel") }}
      </button>
      <button
        v-if="store.object && !store.layerVisible(store.object, 'mask')"
        @click="store.revealManualMask()"
      >
        {{ t("Show mask") }}
      </button>
    </template>
    <template v-else>
      <strong>{{ toolLabel(store.tool) }}</strong>
      <span class="manual-target">{{
        objectNumber
          ? t("Object {number}", { number: objectNumber })
          : t("New object")
      }}</span>
      <template v-if="store.tool === 'polygon'">
        <div
          class="manual-modes"
          role="group"
          :aria-label="t('Polygon operation')"
        >
          <button
            v-for="mode in ['add', 'subtract'] as const"
            :key="mode"
            :disabled="store.manualBusy"
            :aria-pressed="store.polygonMode === mode"
            :class="{ active: store.polygonMode === mode }"
            @click="store.polygonMode = mode"
          >
            {{ t(mode === "add" ? "Add" : "Subtract") }}
          </button>
        </div>
        <button
          :disabled="store.polygonVertices < 3"
          :title="t('Finish polygon · Enter')"
          @click="$emit('finish')"
        >
          {{ t("Finish") }}
        </button>
        <button
          :disabled="!store.manualBusy"
          :title="t('Cancel drawing · Esc')"
          @click="$emit('cancel')"
        >
          {{ t("Cancel") }}
        </button>
      </template>
      <template v-else>
        <label class="manual-size"
          >{{ t("Size") }}
          <input
            type="number"
            min="1"
            max="512"
            step="1"
            :disabled="store.manualBusy"
            :value="size"
            :aria-label="t('Brush diameter in image pixels')"
            @change="sizeChanged"
          />
          <span>px</span></label
        >
        <input
          class="manual-size-slider"
          type="range"
          min="1"
          max="512"
          :disabled="store.manualBusy"
          :value="size"
          :aria-label="t('Brush diameter slider')"
          @input="sizeChanged"
        />
      </template>
      <span
        v-if="store.manualBlocked"
        class="manual-blocked"
        :title="t(store.manualBlocked)"
        >{{ t(store.manualBlocked) }}</span
      >
      <button
        v-if="store.manualBlocked === 'Show the mask to edit it.'"
        @click="store.revealManualMask()"
      >
        {{ t("Show mask") }}
      </button>
    </template>
  </div>
</template>
