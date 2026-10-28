<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { NModal } from "naive-ui";
import { t } from "../i18n";
import { useProject } from "../stores/project";
import BoxPaddingControls from "./BoxPaddingControls.vue";
const store = useProject();
let context: {
  image: string | undefined;
  session: string | undefined;
  annotation: typeof store.annotation;
  selected: string | null;
} | null = null;
const selected = ref(false);
const label = computed(() =>
  selected.value
    ? store.object?.box
      ? "Recalculate box from mask"
      : "Create box from mask"
    : "Create missing boxes from masks",
);
const valid = computed(() => {
  const p = store.boxPadding;
  const numbers = [p.box_padding_pixels, p.box_padding_ratio];
  const targets = selected.value
    ? [store.object]
    : (store.annotation?.instances ?? []);
  return (
    !store.navigating &&
    numbers.every(
      (n) => typeof n === "number" && Number.isFinite(n) && n >= 0,
    ) &&
    targets.some(
      (o) =>
        o &&
        !o.locked &&
        (selected.value || !o.box) &&
        (o.mask || o.polygons.length),
    )
  );
});
function close() {
  store.boxConversion = null;
}
function sameContext() {
  return (
    context &&
    context.image === store.current?.id &&
    context.session === store.meta?.session &&
    context.annotation === store.annotation &&
    (!selected.value || context.selected === store.selected) &&
    !store.navigating
  );
}
watch(
  () => store.boxConversion,
  (value) => {
    if (value) selected.value = value === "selected";
    context = value
      ? {
          image: store.current?.id,
          session: store.meta?.session,
          annotation: store.annotation,
          selected: store.selected,
        }
      : null;
  },
  { immediate: true, flush: "sync" },
);
watch(
  () => [
    store.current?.id,
    store.meta?.session,
    store.annotation,
    store.selected,
    store.navigating,
  ],
  () => {
    if (store.boxConversion && !sameContext()) close();
  },
  { flush: "sync" },
);
function confirm() {
  if (!store.boxConversion || !sameContext() || !valid.value) return;
  const one = selected.value,
    recalculate = one && !!store.object?.box;
  close();
  void store.boxesFromMasks(one, recalculate);
}
</script>
<template>
  <NModal
    :show="store.boxConversion !== null"
    preset="card"
    :title="t(label)"
    :style="{ width: '480px', maxWidth: 'calc(100vw - 32px)' }"
    @update:show="!$event && close()"
  >
    <p class="clear-image-path">{{ store.current?.path }}</p>
    <p v-if="!selected" class="muted">
      {{
        t(
          "Add boxes to unlocked masks without a detection box. Existing boxes are kept.",
        )
      }}
    </p>
    <BoxPaddingControls />
    <div class="clear-annotations-footer">
      <button @click="close">{{ t("Cancel") }}</button>
      <button class="primary" :disabled="!valid" @click="confirm">
        {{ t(label) }}
      </button>
    </div>
  </NModal>
</template>
