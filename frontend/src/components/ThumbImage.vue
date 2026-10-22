<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from "vue";
import { useProject } from "../stores/project";
import { thumbnail } from "../thumbnails";
const props = defineProps<{ id: string }>(),
  src = ref(""),
  controller = new AbortController();
onMounted(async () => {
  try {
    src.value = await thumbnail(
      props.id,
      controller.signal,
      useProject().meta?.session ?? useProject().meta?.id ?? "",
    );
  } catch {
    /* unloaded or unavailable */
  }
});
onBeforeUnmount(() => controller.abort());
</script>
<template>
  <img v-if="src" :src="src" alt="" /><span
    v-else
    class="thumb-placeholder"
  ></span>
</template>
