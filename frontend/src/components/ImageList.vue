<script setup lang="ts">
import { t } from "../i18n";
import { computed, ref } from "vue";
import { useProject } from "../stores/project";
const store = useProject(),
  tree = ref(true),
  expanded = ref(new Set<string>());
const rows = computed(() => {
  const output: Array<{
    key: string;
    name: string;
    depth: number;
    folder: boolean;
    id?: string;
    open?: boolean;
  }> = [];
  const seen = new Set<string>();
  for (const image of store.filtered) {
    const parts = image.path.split("/");
    let path = "",
      show = true;
    if (tree.value)
      for (let depth = 0; depth < parts.length - 1; depth++) {
        path += (path ? "/" : "") + parts[depth];
        if (!show) break;
        if (!seen.has(path)) {
          seen.add(path);
          output.push({
            key: path,
            name: parts[depth],
            depth,
            folder: true,
            open: expanded.value.has(path) || !!store.search,
          });
        }
        show = expanded.value.has(path) || !!store.search;
      }
    if (show)
      output.push({
        key: image.id,
        id: image.id,
        name: tree.value ? parts.at(-1)! : image.path,
        depth: tree.value ? parts.length - 1 : 0,
        folder: false,
      });
  }
  return output;
});
function toggle(path: string) {
  if (expanded.value.has(path)) expanded.value.delete(path);
  else expanded.value.add(path);
}
function all(open: boolean) {
  expanded.value.clear();
  if (open)
    for (const im of store.images) {
      const parts = im.path.split("/");
      parts.pop();
      let path = "";
      for (const part of parts) {
        path += (path ? "/" : "") + part;
        expanded.value.add(path);
      }
    }
}
const scroll = ref(0),
  start = computed(() => Math.max(0, Math.floor(scroll.value / 31) - 4));
</script>
<template>
  <div class="image-controls">
    <div class="row">
      <strong>{{ t("Images") }}</strong
      ><span class="muted">{{ store.images.length }}</span>
    </div>
    <input
      v-model="store.search"
      :placeholder="t('Search images or folders…')"
    />
    <div class="row">
      <select v-model="tree">
        <option :value="true">{{ t("Tree") }}</option>
        <option :value="false">{{ t("Flat") }}</option></select
      ><button @click="all(true)">{{ t("Expand all") }}</button
      ><button @click="all(false)">{{ t("Collapse all") }}</button>
    </div>
  </div>
  <div
    class="file-list"
    @scroll="scroll = ($event.target as HTMLElement).scrollTop"
  >
    <div :style="{ height: start * 31 + 'px' }"></div>
    <button
      v-for="row in rows.slice(start, start + 40)"
      :key="row.key"
      class="file"
      :class="{ active: row.id === store.current?.id }"
      :style="{ paddingLeft: 10 + row.depth * 14 + 'px' }"
      :title="
        row.folder ? row.key : store.images.find((i) => i.id === row.id)?.path
      "
      @click="
        row.folder
          ? toggle(row.key)
          : store.load(store.images.find((i) => i.id === row.id)!)
      "
    >
      <span v-if="row.folder">{{ row.open ? "▾" : "▸" }} ▱</span
      ><span>{{ row.name }}</span>
    </button>
    <div
      :style="{ height: Math.max(0, rows.length - start - 40) * 31 + 'px' }"
    ></div>
  </div>
</template>
