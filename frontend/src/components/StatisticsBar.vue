<script setup lang="ts">
import { t, uiError } from "../i18n";
import { onBeforeUnmount, ref, watch } from "vue";
import { request, type ProjectStatistics } from "../api";
import StatisticsDrawer from "./StatisticsDrawer.vue";
import { useProject } from "../stores/project";
import { reviewStates } from "../review";
const store = useProject();
const props = defineProps<{ active: boolean }>();
const stats = ref<ProjectStatistics | null>(null),
  error = ref(""),
  detailsOpen = ref(false),
  includeExcluded = ref(false);
let generation = 0,
  timer: ReturnType<typeof setTimeout> | undefined;
async function refresh(reset = false) {
  if (timer) clearTimeout(timer);
  const token = ++generation,
    project = store.meta?.session ?? store.meta?.id,
    task = store.task;
  if (reset) stats.value = null;
  if (!project || document.hidden) return;
  try {
    const result = await request<ProjectStatistics>(
      "/project/statistics?task=" +
        task +
        "&include_excluded=" +
        includeExcluded.value,
    );
    if (
      generation !== token ||
      (store.meta?.session ?? store.meta?.id) !== project ||
      store.task !== task
    )
      return;
    stats.value = result; // The latest request remains valid across backend restarts.
    error.value = "";
  } catch (e) {
    if (generation === token) error.value = String(e);
  } finally {
    if (generation === token)
      timer = setTimeout(
        () => void refresh(),
        props.active || stats.value?.status !== "ready" ? 2000 : 10000,
      );
  }
}
watch(
  [
    () => store.meta?.id,
    () => store.meta?.session,
    () => store.task,
    () => includeExcluded.value,
  ],
  () => void refresh(true),
  { immediate: true },
);
watch(
  () => store.saving,
  (saving, previous) => {
    if (previous && !saving) void refresh();
  },
);
watch(
  () => props.active,
  () => void refresh(),
);
function visibility() {
  void refresh();
}
document.addEventListener("visibilitychange", visibility);
onBeforeUnmount(() => {
  generation++;
  if (timer) clearTimeout(timer);
  document.removeEventListener("visibilitychange", visibility);
});
</script>
<template>
  <div v-if="store.meta" class="statistics-bar" aria-live="polite">
    <strong>{{
      store.task === "detection" ? t("Detection") : t("Segmentation")
    }}</strong>
    <span v-if="error" :title="uiError(error)">{{
      t("Statistics unavailable")
    }}</span>
    <span v-else-if="!stats || stats.status !== 'ready'">{{
      t("Loading statistics…")
    }}</span>
    <template v-else>
      <span v-if="!stats.total">{{ t("No images") }}</span>
      <span v-else
        >{{ t("Approved") }}
        <b>{{ stats.counts.ok || 0 }}/{{ stats.total }}</b></span
      >
      <span
        v-for="state in reviewStates"
        :key="state.value"
        :title="t(state.description)"
        ><i :style="{ background: state.color }" /> {{ t(state.label) }}
        <b>{{ stats.counts[state.value] }}</b></span
      >
      <span
        class="geometry-counts"
        :title="
          t(
            includeExcluded
              ? 'Saved boxes and masks, including excluded images'
              : 'Saved boxes and masks, excluding excluded images',
          )
        "
        >{{ t("Boxes") }} <b>{{ stats.boxes }}</b> · {{ t("Masks") }}
        <b>{{ stats.masks }}</b></span
      >
      <span v-if="stats.invalid_images" class="statistics-warning">{{
        t("Counts exclude {count} images with unreadable annotations.", {
          count: stats.invalid_images,
        })
      }}</span>
    </template>
    <button
      :title="t('Per-class annotation counts')"
      @click="detailsOpen = true"
    >
      {{ t("More statistics") }}
    </button>
    <StatisticsDrawer
      v-model:show="detailsOpen"
      v-model:include-excluded="includeExcluded"
      :stats="stats"
      :error="error"
    />
  </div>
</template>
<style scoped>
.statistics-bar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 9px 20px;
  padding: 9px 16px;
  border-bottom: 1px solid var(--line);
  background: #fff;
  font-size: 12px;
}
.statistics-bar span {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  color: #576578;
}
.geometry-counts {
  border-left: 1px solid var(--line);
  padding-left: 16px;
}
.statistics-bar button {
  margin-left: auto;
  padding: 3px 8px;
  font-size: 12px;
}
.statistics-bar b {
  color: #283445;
  font-variant-numeric: tabular-nums;
}
</style>
