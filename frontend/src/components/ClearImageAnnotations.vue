<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { NModal } from "naive-ui";
import { t } from "../i18n";
import { useProject } from "../stores/project";
const props = defineProps<{ show: boolean }>();
const emit = defineEmits<{ "update:show": [boolean] }>();
const store = useProject();
const includeLocked = ref(false);
let context: {
  image: string | undefined;
  session: string | undefined;
  annotation: typeof store.annotation;
} | null = null;
const targets = computed(
  () =>
    store.annotation?.instances.filter(
      (o) => includeLocked.value || !o.locked,
    ) ?? [],
);
const locked = computed(
  () => store.annotation?.instances.filter((o) => o.locked).length ?? 0,
);
function close() {
  emit("update:show", false);
}
watch(
  () => props.show,
  (show) => {
    if (show) {
      includeLocked.value = false;
      context = {
        image: store.current?.id,
        session: store.meta?.session,
        annotation: store.annotation,
      };
    } else context = null;
  },
  { immediate: true },
);
watch(
  () => [
    store.current?.id,
    store.meta?.session,
    store.annotation,
    store.navigating,
  ],
  () => {
    if (
      props.show &&
      (!context ||
        context.image !== store.current?.id ||
        context.session !== store.meta?.session ||
        context.annotation !== store.annotation ||
        store.navigating)
    )
      close();
  },
  { flush: "sync" },
);
function confirm() {
  if (
    !context ||
    context.image !== store.current?.id ||
    context.session !== store.meta?.session ||
    context.annotation !== store.annotation ||
    !targets.value.length ||
    store.navigating
  ) {
    close();
    return;
  }
  store.clearImageAnnotations(includeLocked.value);
  close();
}
</script>
<template>
  <NModal
    :show="show"
    preset="card"
    :title="t('Clear image annotations…')"
    class="clear-annotations-dialog"
    :style="{ width: '440px', maxWidth: 'calc(100vw - 32px)' }"
    @update:show="emit('update:show', $event)"
  >
    <p class="clear-image-path">{{ store.current?.path }}</p>
    <p>
      {{
        t("Remove {count} objects, including their boxes, masks and prompts?", {
          count: targets.length,
        })
      }}
    </p>
    <label v-if="locked" class="include-locked"
      ><input v-model="includeLocked" type="checkbox" />{{
        t("Include locked objects ({count})", { count: locked })
      }}</label
    >
    <p v-if="locked && !includeLocked" class="muted">
      {{ t("{count} locked objects will be kept.", { count: locked }) }}
    </p>
    <p class="muted">
      {{
        t(
          "Image tags, notes and project classes are kept. Review returns to Not reviewed; this does not confirm an empty image. Undo restores the operation.",
        )
      }}
    </p>
    <div class="clear-annotations-footer">
      <button @click="close">{{ t("Cancel") }}</button
      ><button
        class="danger-button"
        :disabled="!targets.length || store.navigating"
        @click="confirm"
      >
        {{ t("Clear annotations") }}
      </button>
    </div>
  </NModal>
</template>
