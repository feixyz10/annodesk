<script setup lang="ts">
import { computed, nextTick, ref, watch } from "vue";
import { NPopover } from "naive-ui";
import { useProject } from "../stores/project";
import { layerKinds, layerNames } from "../visibility";
import { t } from "../i18n";
import Icon from "./Icon.vue";
const store = useProject();
const open = ref(false);
const panel = ref<HTMLElement>();
const trigger = ref<HTMLButtonElement>();
watch(open, async (value) => {
  if (value) {
    store.hovered = null;
    await nextTick();
    panel.value?.focus();
  }
});
function closeWithKeyboard() {
  open.value = false;
  trigger.value?.focus();
}
const state = computed(() => {
  const shown = layerKinds.filter((k) => store.globalLayers[k]).length;
  return shown === 0
    ? "All hidden"
    : shown === layerKinds.length
      ? "All visible"
      : "Partially visible";
});
const preset = computed(() => {
  const g = store.globalLayers;
  return g.box && g.mask && g.prompts
    ? "all"
    : g.box && !g.mask && !g.prompts
      ? "detection"
      : !g.box && g.mask && g.prompts
        ? "segmentation"
        : "custom";
});
watch([() => store.current?.id, () => store.meta?.session], () => {
  open.value = false;
});
function checked(event: Event) {
  return (event.target as HTMLInputElement).checked;
}
</script>
<template>
  <NPopover
    v-model:show="open"
    trigger="click"
    placement="bottom-end"
    :show-arrow="false"
  >
    <template #trigger>
      <button
        ref="trigger"
        @keydown.esc.stop.prevent="closeWithKeyboard"
        :class="['visibility-trigger', { active: open }]"
        :disabled="!store.meta"
        :aria-label="t('Layers')"
        :title="`${t('Layers')} · ${t(state)}`"
        :aria-expanded="open"
        aria-haspopup="dialog"
      >
        <Icon name="layers" />
      </button>
    </template>
    <section
      ref="panel"
      tabindex="-1"
      @keydown.esc.stop.prevent="closeWithKeyboard"
      class="visibility-panel"
      role="dialog"
      :aria-label="t('Layers')"
    >
      <header>
        <strong>{{ t("Layers") }}</strong
        ><button :aria-label="t('Close')" @click="open = false">
          <Icon name="close" />
        </button>
      </header>
      <p>{{ t("Applies to all images in this project.") }}</p>
      <div
        class="visibility-presets"
        role="group"
        :aria-label="t('View presets')"
      >
        <button
          v-for="item in [
            ['detection', 'Detection view'],
            ['segmentation', 'Segmentation view'],
            ['all', 'All layers'],
          ] as const"
          :key="item[0]"
          :aria-pressed="preset === item[0]"
          @click="store.applyView(item[0])"
        >
          {{ t(item[1]) }}
        </button>
      </div>
      <label
        v-for="kind in layerKinds"
        :key="kind"
        class="visibility-layer-option"
      >
        <input
          type="checkbox"
          :aria-label="t('Global: {layer}', { layer: t(layerNames[kind]) })"
          :checked="store.globalLayers[kind]"
          @change="store.setLayer('global', kind, checked($event))"
        />
        <span>{{ t(layerNames[kind]) }}</span>
      </label>
      <p>
        {{
          t(
            "Use the Objects column headings for this image, geometry icons for one layer, and the eye for a whole object.",
          )
        }}
      </p>
      <p class="visibility-note">
        {{ t("Display only. Saving, export and processing are unchanged.") }}
      </p>
    </section>
  </NPopover>
</template>
