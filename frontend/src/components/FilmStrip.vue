<script setup lang="ts">
import { t } from "../i18n";
import { computed, ref, watch, nextTick } from "vue";
import { useProject } from "../stores/project";
import ThumbImage from "./ThumbImage.vue";
const store = useProject(),
  el = ref<HTMLDivElement>(),
  left = ref(0);
const stride = 120,
  windowSize = 18,
  start = computed(() =>
    Math.min(
      Math.max(0, store.filtered.length - windowSize),
      Math.max(0, Math.floor(left.value / stride) - 3),
    ),
  ),
  visible = computed(() =>
    store.filtered.slice(start.value, start.value + windowSize),
  );
let generation = 0;
function setLeft(value: number) {
  left.value = value;
  if (el.value) el.value.scrollLeft = value;
}
watch(
  [
    () => store.search,
    () => store.meta?.session,
    () => store.meta?.id,
    () => store.meta?.root,
  ],
  () => {
    generation++;
    setLeft(0);
  },
);
watch(
  () => store.filtered.length,
  (count) => {
    const maximum = Math.max(
      0,
      count * stride - (el.value?.clientWidth ?? stride),
    );
    if (left.value > maximum) setLeft(maximum);
  },
);
function wheel(e: WheelEvent) {
  if (el.value && Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
    e.preventDefault();
    el.value.scrollLeft += e.deltaY;
  }
}
watch(
  () => store.current?.id,
  async () => {
    const request = ++generation;
    await nextTick();
    if (request !== generation) return;
    const index = store.filtered.findIndex((i) => i.id === store.current?.id);
    if (el.value)
      setLeft(
        Math.max(
          0,
          Math.min(
            Math.max(0, store.filtered.length * stride - el.value.clientWidth),
            index * stride - el.value.clientWidth / 2 + 55,
          ),
        ),
      );
  },
);
</script>
<template>
  <div class="film-wrap">
    <button
      :title="t('Scroll previews left')"
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
      <span :style="{ width: start * stride + 'px', flexShrink: 0 }"></span
      ><button
        v-for="image in visible"
        :key="(store.meta?.session ?? store.meta?.id ?? '') + image.id"
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
            Math.max(0, store.filtered.length - start - visible.length) *
              stride +
            'px',
          flexShrink: 0,
        }"
      ></span>
    </div>
    <button
      :title="t('Scroll previews right')"
      @click="el?.scrollBy({ left: 360, behavior: 'smooth' })"
    >
      ›
    </button>
  </div>
</template>
