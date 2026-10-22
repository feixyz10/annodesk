<script setup lang="ts">
import { t } from "../i18n";
import { computed, nextTick, ref, watch } from "vue";
import { NModal } from "naive-ui";
import { useProject } from "../stores/project";
const store = useProject(),
  query = ref(""),
  active = ref(0),
  search = ref<HTMLInputElement>(),
  list = ref<HTMLDivElement>();
const matches = computed(() =>
  (store.meta?.classes ?? [])
    .filter((c) =>
      `${c.name} ${c.index}`
        .toLowerCase()
        .includes(query.value.trim().toLowerCase()),
    )
    .slice(0, 100),
);
watch(query, () => {
  active.value = 0;
});
watch(
  () => [store.selected, store.current?.id],
  () => {
    store.classPickerOpen = false;
  },
);
watch(
  () => store.classPickerOpen,
  (open) => {
    if (open) {
      query.value = "";
      active.value = 0;
    }
  },
);
function choose(id: string) {
  if (!store.object || store.object.locked || store.navigating) return;
  store.assign(id);
  store.classPickerOpen = false;
}
async function move(delta: number) {
  active.value =
    (active.value + delta + matches.value.length) %
    Math.max(matches.value.length, 1);
  await nextTick();
  list.value
    ?.querySelector(`[data-index="${active.value}"]`)
    ?.scrollIntoView({ block: "nearest" });
}
function key(event: KeyboardEvent) {
  event.stopPropagation();
  if (event.isComposing) return;
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    void move(event.key === "ArrowDown" ? 1 : -1);
  } else if (event.key === "Enter") {
    event.preventDefault();
    const item = matches.value[active.value];
    if (item) choose(item.id);
  } else if (event.key === "Escape") store.classPickerOpen = false;
}
</script>
<template>
  <NModal
    v-model:show="store.classPickerOpen"
    preset="card"
    :title="t('Change class')"
    class="class-picker"
    :style="{ width: '380px', maxWidth: 'calc(100vw - 32px)' }"
    @after-enter="search?.focus()"
  >
    <div @keydown="key">
      <p class="muted">{{ t("Assign a class to the selected annotation.") }}</p>
      <input
        ref="search"
        v-model="query"
        :aria-label="t('Search classes by name or ID')"
        :placeholder="t('Search by class name or ID…')"
        role="combobox"
        aria-controls="class-picker-options"
        :aria-expanded="true"
        :aria-activedescendant="
          matches.length ? `class-option-${active}` : undefined
        "
        autocomplete="off"
      />
      <div
        id="class-picker-options"
        ref="list"
        class="class-picker-list"
        role="listbox"
        :aria-label="t('Matching classes')"
      >
        <button
          v-for="(c, i) in matches"
          :id="`class-option-${i}`"
          :key="c.id"
          :data-index="i"
          role="option"
          :aria-selected="i === active"
          :class="{ active: i === active }"
          @click="choose(c.id)"
        >
          <i :style="{ background: c.color }"></i><span>{{ c.name }}</span
          ><small>ID {{ c.index }}</small>
          <span v-if="store.object?.class_id === c.id" class="muted">{{
            t("Current")
          }}</span>
        </button>
        <p v-if="!matches.length" class="muted">
          {{ t("No matching classes.") }}
        </p>
      </div>
      <p class="muted picker-help">
        {{ t("↑ ↓ navigate · Enter assign · Esc cancel") }}
      </p>
    </div>
  </NModal>
</template>
