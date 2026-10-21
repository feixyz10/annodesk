<script setup lang="ts">
import { computed, ref, watch, nextTick } from "vue";
import { useProject } from "../stores/project";
import ThumbImage from "./ThumbImage.vue";
const store = useProject(),
  el = ref<HTMLDivElement>(),
  left = ref(0);
const start = computed(() => Math.max(0, Math.floor(left.value / 120) - 3)),
  visible = computed(() => store.filtered.slice(start.value, start.value + 18));
function wheel(e: WheelEvent) {
  if (el.value && Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
    e.preventDefault();
    el.value.scrollLeft += e.deltaY;
  }
}
watch(
  () => store.current?.id,
  async () => {
    await nextTick();
    const index = store.filtered.findIndex((i) => i.id === store.current?.id);
    if (el.value)
      el.value.scrollLeft = Math.max(
        0,
        index * 120 - el.value.clientWidth / 2 + 55,
      );
  },
);
</script>
<template>
  <div class="film-wrap">
    <button
      title="Scroll previews left"
      @click="el?.scrollBy({ left: -360, behavior: 'smooth' })"
    >
      ‹
    </button>
    <div
      ref="el"
      class="film"
      @scroll="left = el?.scrollLeft ?? 0"
      @wheel="wheel"
    >
      <span :style="{ width: start * 120 + 'px', flexShrink: 0 }"></span
      ><button
        v-for="image in visible"
        :key="(store.meta?.id ?? '') + image.id"
        class="thumb"
        :class="{ active: image.id === store.current?.id }"
        :title="image.path"
        @click="store.load(image)"
      >
        <ThumbImage :id="image.id" /><span>{{
          image.path.split("/").at(-1)
        }}</span></button
      ><span
        :style="{
          width:
            Math.max(0, store.filtered.length - start - visible.length) * 120 +
            'px',
          flexShrink: 0,
        }"
      ></span>
    </div>
    <button
      title="Scroll previews right"
      @click="el?.scrollBy({ left: 360, behavior: 'smooth' })"
    >
      ›
    </button>
  </div>
</template>
