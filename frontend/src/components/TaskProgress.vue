<script setup lang="ts">
import { t, statusLabel } from "../i18n";
defineProps<{
  completed: number;
  total: number;
  phase: string;
  running: boolean;
}>();
</script>
<template>
  <div class="task-progress" :aria-busy="running">
    <progress
      v-if="
        running &&
        ['preflight', 'preparing', 'loading', 'packaging'].includes(phase)
      "
      :aria-label="statusLabel(phase)"
    />
    <progress
      v-else
      :value="completed"
      :max="Math.max(1, total)"
      :aria-label="t('Finished images')"
    />
    <span class="muted" role="status">{{
      phase === "loading"
        ? t("Loading models…")
        : phase === "preflight"
          ? t("Scanning annotations…")
          : phase === "packaging"
            ? t("Writing export metadata…")
            : statusLabel(phase)
    }}</span>
  </div>
</template>
<style scoped>
progress {
  width: 100%;
  height: 8px;
  appearance: none;
  border: 0;
  border-radius: 8px;
  background: #e5ebf5;
  overflow: hidden;
  accent-color: var(--accent);
}
progress::-webkit-progress-bar {
  background: #e5ebf5;
  border-radius: 8px;
}
progress::-webkit-progress-value {
  background: #315fe9;
  border-radius: 8px;
}
progress::-moz-progress-bar {
  background: #315fe9;
  border-radius: 8px;
}
progress:not([value])::-webkit-progress-bar {
  background: linear-gradient(100deg, #e5ebf5 25%, #7999ef 50%, #e5ebf5 75%);
  background-size: 200% 100%;
  animation: task-preparing 1.5s linear infinite;
}
@keyframes task-preparing {
  to {
    background-position: -200% 0;
  }
}
@media (prefers-reduced-motion: reduce) {
  progress:not([value])::-webkit-progress-bar {
    animation: none;
  }
}
.task-progress {
  display: grid;
  gap: 4px;
  margin: 10px 0;
}
</style>
