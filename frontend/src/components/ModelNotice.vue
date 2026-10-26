<script setup lang="ts">
import { computed } from "vue";
import type { ModelsConfig } from "../api";
import { t, taskLabel } from "../i18n";
const props = defineProps<{
  config: ModelsConfig | null;
  task: "detection" | "segmentation";
  modelId: string;
  settingsButton?: boolean;
}>();
const emit = defineEmits<{ settings: [] }>();
const selected = computed(() =>
  props.config?.models.find(
    (model) =>
      model.id === props.modelId &&
      (model.task || "segmentation") === props.task,
  ),
);
const missing = computed(() => props.config?.missing_dependencies || []);
const unavailable = computed(
  () => !!props.config && !selected.value?.available,
);
</script>
<template>
  <section
    v-if="unavailable || missing.length"
    class="model-notice"
    role="status"
    :aria-label="t('Model setup')"
  >
    <div class="model-notice-copy">
      <p v-if="unavailable">
        <template v-if="selected">
          {{
            t(
              "Model {model} was not found locally. Check its directory in models.json, then Reload in Models.",
              { model: selected.id },
            )
          }}
        </template>
        <template v-else>
          {{
            t(
              "No {task} model is configured. Add a local model in models.json, then Reload in Models.",
              { task: taskLabel(task) },
            )
          }}
        </template>
      </p>
      <p v-if="missing.length">
        {{
          t(
            "Inference dependencies missing: {dependencies}. Reinstall AnnoDesk with dependencies in the backend environment, then restart.",
            { dependencies: missing.join(", ") },
          )
        }}
      </p>
      <p class="model-notice-hint">
        {{
          t(
            "Manual annotation remains available. Models are never downloaded automatically.",
          )
        }}
      </p>
    </div>
    <button v-if="settingsButton" @click="emit('settings')">
      {{ t("Open Models") }}
    </button>
  </section>
</template>
<style scoped>
.model-notice {
  display: flex;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 8px 16px;
  padding: 10px 14px;
  background: #fff9eb;
  border-bottom: 1px solid #ead7ae;
  color: #6d4d17;
}
.model-notice-copy {
  flex: 1 1 360px;
  min-width: 0;
  overflow-wrap: anywhere;
}
.model-notice p {
  margin: 0;
}
.model-notice p + p {
  margin-top: 4px;
}
.model-notice-hint {
  font-size: 12px;
}
.model-notice button {
  flex-shrink: 0;
}
</style>
