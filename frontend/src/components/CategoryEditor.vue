<script setup lang="ts">
import { ref, watch, onBeforeUnmount } from "vue";
import { request, type Category } from "../api";
import { useProject } from "../stores/project";
import { t } from "../i18n";
const props = defineProps<{ category: Category }>();
const emit = defineEmits<{ saved: [Category]; error: [string] }>();
const store = useProject();
const name = ref(props.category.name),
  color = ref(props.category.color),
  saving = ref(false);
let generation = 0;
watch(
  [
    () => props.category.id,
    () => props.category.name,
    () => props.category.color,
    () => store.meta?.session,
    () => store.meta?.id,
    () => store.meta?.root,
  ],
  () => {
    generation++;
    name.value = props.category.name;
    color.value = props.category.color;
    saving.value = false;
  },
  { flush: "sync" },
);
onBeforeUnmount(() => {
  generation++;
});
async function save() {
  if (saving.value) return;
  const token = generation;
  const draft = { name: name.value, color: color.value };
  saving.value = true;
  try {
    const updated = await request<Category>(
      `/categories/${props.category.id}`,
      "PATCH",
      draft,
    );
    if (token !== generation) return;
    name.value = updated.name;
    color.value = updated.color;
    emit("saved", updated);
  } catch (error) {
    if (token !== generation) return;
    name.value = props.category.name;
    color.value = props.category.color;
    emit("error", String(error));
  } finally {
    if (token === generation) saving.value = false;
  }
}
</script>
<template>
  <div class="category-editor">
    <input
      type="color"
      v-model="color"
      :disabled="saving"
      :aria-label="
        t(category.index === undefined ? 'Tag color' : 'Class color')
      "
      @change="save"
    />
    <input
      v-model="name"
      :disabled="saving"
      :aria-label="t(category.index === undefined ? 'Tag name' : 'Class name')"
      @change="save"
    />
    <span v-if="category.index !== undefined">ID {{ category.index }}</span>
  </div>
</template>
