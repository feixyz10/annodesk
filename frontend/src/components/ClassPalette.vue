<script setup lang="ts">
import { computed, ref } from "vue";
import { useProject } from "../stores/project";
const store = useProject(),
  search = ref("");
const classes = computed(
  () =>
    store.meta?.classes.filter((c) =>
      c.name.toLowerCase().includes(search.value.toLowerCase()),
    ) ?? [],
);
async function add() {
  const name = prompt("New class name");
  if (name) await store.addClass(name);
}
</script>
<template>
  <div class="palette">
    <div class="section">
      <div class="row">
        <strong>Class palette</strong
        ><button @click="store.selected = null">New objects</button>
      </div>
      <p class="context">
        {{
          store.object
            ? "Assign to selected object"
            : "New objects: " +
              (store.meta?.classes.find((c) => c.id === store.defaultClass)
                ?.name ?? "Unassigned")
        }}
      </p>
      <input v-model="search" placeholder="Search classes…" />
    </div>
    <div class="class-list">
      <button
        v-for="c in classes"
        :key="c.id"
        class="class-item"
        :class="{
          active: (store.object?.class_id ?? store.defaultClass) === c.id,
        }"
        @click="store.assign(c.id)"
      >
        <i :style="{ background: c.color }"></i><span>{{ c.name }}</span
        ><small>ID {{ c.index }}</small>
      </button>
    </div>
    <div class="section"><button @click="add">Add class</button></div>
  </div>
</template>
