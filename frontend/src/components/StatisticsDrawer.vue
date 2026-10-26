<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { NModal } from "naive-ui";
import { t } from "../i18n";
import { useProject } from "../stores/project";
import { type ProjectStatistics, type ClassStatistics } from "../api";
const props = defineProps<{
  show: boolean;
  stats: ProjectStatistics | null;
  includeExcluded: boolean;
  error: string;
}>();
const emit = defineEmits<{
  "update:show": [boolean];
  "update:includeExcluded": [boolean];
}>();
const store = useProject(),
  view = ref<"table" | "bars">("table"),
  query = ref(""),
  page = ref(1);
function name(row: ClassStatistics) {
  return (
    store.meta?.classes.find((c) => c.id === row.class_id)?.name ??
    row.name ??
    t(row.class_id ? "Unknown class" : "Unassigned")
  );
}
const rows = computed(() =>
  (props.stats?.classes ?? [])
    .filter((row) =>
      `${row.index ?? ""} ${name(row)}`
        .toLowerCase()
        .includes(query.value.trim().toLowerCase()),
    )
    .sort(
      (a, b) =>
        b.boxes + b.masks - a.boxes - a.masks ||
        (a.index ?? Infinity) - (b.index ?? Infinity),
    ),
);
const pageSize = computed(() => (view.value === "table" ? 50 : 20)),
  pages = computed(() =>
    Math.max(1, Math.ceil(rows.value.length / pageSize.value)),
  );
const visible = computed(() =>
  rows.value.slice(
    (page.value - 1) * pageSize.value,
    page.value * pageSize.value,
  ),
);
const max = computed(() =>
  Math.max(1, ...rows.value.flatMap((row) => [row.boxes, row.masks])),
);
watch([query, view], () => {
  page.value = 1;
});
watch(pages, (value) => {
  page.value = Math.min(page.value, value);
});
watch(
  () => store.meta?.session,
  () => {
    query.value = "";
    page.value = 1;
  },
);
</script>
<template>
  <NModal
    :show="show"
    @update:show="emit('update:show', $event)"
    preset="card"
    :title="t('Annotation statistics')"
    class="statistics-window"
    style="width: 900px; max-width: 92vw; max-height: 85vh; overflow: hidden"
    content-style="overflow:auto;min-height:0"
  >
    <div class="statistics-content">
      <p class="muted statistics-explanation">
        {{
          t(
            "Saved annotations across this project, including manual and generated results. SAM prompt boxes are not detection boxes. An object with both a box and a mask counts once in each.",
          )
        }}
      </p>
      <p class="muted">
        {{
          t(
            "Object totals include prompt-only drafts; box and mask totals count saved geometry.",
          )
        }}
      </p>
      <label class="statistics-scope"
        ><input
          type="checkbox"
          :checked="includeExcluded"
          @change="
            emit(
              'update:includeExcluded',
              ($event.target as HTMLInputElement).checked,
            )
          "
        />{{ t("Include excluded images") }}</label
      >
      <p v-if="error" role="alert">{{ t("Statistics unavailable") }}</p>
      <p v-else-if="!stats || stats.status !== 'ready'">
        {{ t("Loading statistics…") }}
      </p>
      <template v-else>
        <div class="statistics-summary">
          <span
            >{{ t("Boxes") }} <b>{{ stats.boxes }}</b></span
          ><span
            >{{ t("Masks") }} <b>{{ stats.masks }}</b></span
          ><span
            >{{ t("Objects") }} <b>{{ stats.instances }}</b></span
          >
        </div>
        <p v-if="stats.invalid_images" class="statistics-warning">
          {{
            t("Counts exclude {count} images with unreadable annotations.", {
              count: stats.invalid_images,
            })
          }}
        </p>
        <div class="statistics-controls">
          <input
            v-model="query"
            type="search"
            :aria-label="t('Search classes by name or ID')"
            :placeholder="t('Search by class name or ID…')"
          />
          <div
            class="statistics-view-switch"
            role="group"
            :aria-label="t('Statistics view')"
          >
            <button :aria-pressed="view === 'table'" @click="view = 'table'">
              {{ t("Table") }}</button
            ><button :aria-pressed="view === 'bars'" @click="view = 'bars'">
              {{ t("Bar chart") }}
            </button>
          </div>
        </div>
        <p class="muted">
          {{
            t(
              "Sorted by boxes + masks, highest first. Image counts are unique within each class.",
            )
          }}
        </p>
        <div class="statistics-data">
          <table v-if="view === 'table'" class="class-statistics-table">
            <caption class="sr-only">
              {{
                t("Per-class annotation counts")
              }}
            </caption>
            <thead>
              <tr>
                <th scope="col">{{ t("Class") }}</th>
                <th scope="col">{{ t("Images") }}</th>
                <th scope="col">{{ t("Objects") }}</th>
                <th scope="col">{{ t("Boxes") }}</th>
                <th scope="col">{{ t("Masks") }}</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="row in visible" :key="row.class_id ?? 'unassigned'">
                <th scope="row">
                  <span class="statistics-class-name"
                    ><i :style="{ background: row.color }"></i
                    ><span
                      ><small v-if="row.index !== null"
                        >{{ row.index }} · </small
                      >{{ name(row) }}</span
                    ></span
                  >
                </th>
                <td>{{ row.images }}</td>
                <td>{{ row.instances }}</td>
                <td>{{ row.boxes }}</td>
                <td>{{ row.masks }}</td>
              </tr>
            </tbody>
          </table>
          <div v-else class="class-statistics-chart">
            <div class="statistics-legend">
              <span><i class="box-key"></i>{{ t("Boxes") }}</span
              ><span><i class="mask-key"></i>{{ t("Masks") }}</span>
            </div>
            <div class="statistics-chart-axis">
              <span>0</span><span>{{ max }}</span>
            </div>
            <div
              v-for="row in visible"
              :key="row.class_id ?? 'unassigned'"
              class="statistics-chart-row"
              role="img"
              :aria-label="
                t('{name}: {boxes} boxes, {masks} masks', {
                  name: name(row),
                  boxes: row.boxes,
                  masks: row.masks,
                })
              "
            >
              <div class="statistics-chart-name" :title="name(row)">
                {{ name(row) }}
              </div>
              <div class="statistics-chart-bars">
                <div class="statistics-chart-line">
                  <div class="statistics-chart-track">
                    <div
                      class="statistics-chart-fill box-key"
                      :style="{ width: (row.boxes / max) * 100 + '%' }"
                    ></div>
                  </div>
                  <b>{{ row.boxes }}</b>
                </div>
                <div class="statistics-chart-line">
                  <div class="statistics-chart-track">
                    <div
                      class="statistics-chart-fill mask-key"
                      :style="{ width: (row.masks / max) * 100 + '%' }"
                    ></div>
                  </div>
                  <b>{{ row.masks }}</b>
                </div>
              </div>
            </div>
          </div>
          <p v-if="!rows.length" class="muted">
            {{ t("No matching classes") }}
          </p>
        </div>
        <div class="statistics-pagination">
          <span>{{ t("Page {page} of {pages}", { page, pages }) }}</span
          ><button :disabled="page <= 1" @click="page--">
            {{ t("Previous") }}</button
          ><button :disabled="page >= pages" @click="page++">
            {{ t("Next") }}
          </button>
        </div>
      </template>
    </div>
  </NModal>
</template>
<style scoped>
.statistics-content {
  height: 100%;
  display: flex;
  flex-direction: column;
  gap: 12px;
  font-size: 13px;
  min-height: 0;
}
.statistics-content p {
  margin: 0;
  line-height: 1.6;
}
.statistics-scope {
  display: flex;
  align-items: center;
  gap: 6px;
}
.statistics-summary {
  display: flex;
  flex-wrap: wrap;
  gap: 12px 24px;
}
.statistics-summary b {
  margin-left: 6px;
}
.statistics-warning {
  color: #985d18;
}
.statistics-controls {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 10px;
}
.statistics-controls > input {
  flex: 1;
  min-width: 160px;
}
.statistics-view-switch {
  display: flex;
  gap: 5px;
}
.statistics-view-switch button[aria-pressed="true"] {
  background: #edf2ff;
  border-color: #315fe9;
  color: #2549b8;
}
.statistics-data {
  flex: 1;
  min-height: 0;
  overflow: auto;
}
.class-statistics-table {
  width: 100%;
  border-collapse: collapse;
  min-width: 470px;
}
.class-statistics-table th,
.class-statistics-table td {
  padding: 9px 10px;
  border-bottom: 1px solid var(--line);
  text-align: right;
  font-variant-numeric: tabular-nums;
}
.class-statistics-table thead {
  position: sticky;
  top: 0;
  background: white;
  z-index: 1;
}
.class-statistics-table th:first-child {
  text-align: left;
}
.class-statistics-table tbody th {
  font-weight: 400;
  max-width: 240px;
  overflow-wrap: anywhere;
}
.statistics-class-name {
  display: flex;
  align-items: baseline;
  gap: 7px;
}
.statistics-class-name i,
.statistics-legend i {
  display: inline-block;
  flex: none;
  width: 8px;
  height: 8px;
  border-radius: 2px;
}
.statistics-class-name small {
  color: #65748b;
  font-variant-numeric: tabular-nums;
}
.statistics-legend {
  display: flex;
  gap: 18px;
  margin-bottom: 10px;
}
.statistics-legend span {
  display: flex;
  align-items: center;
  gap: 6px;
}
.box-key {
  background: #315fe9;
}
.mask-key {
  background: #24835d;
}
.statistics-chart-axis {
  margin-left: 140px;
  margin-right: 55px;
  display: flex;
  justify-content: space-between;
  color: #65748b;
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}
.statistics-chart-row {
  display: grid;
  grid-template-columns: 128px minmax(100px, 1fr);
  gap: 12px;
  padding: 12px 0;
  border-bottom: 1px solid var(--line);
  align-items: center;
}
.statistics-chart-name {
  font-size: 12px;
  overflow-wrap: anywhere;
}
.statistics-chart-bars {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.statistics-chart-line {
  display: flex;
  align-items: center;
  gap: 8px;
}
.statistics-chart-track {
  height: 9px;
  background: #edf0f4;
  flex: 1;
}
.statistics-chart-fill {
  height: 100%;
}
.statistics-chart-line b {
  min-width: 47px;
  text-align: right;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
.statistics-pagination {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: 8px;
  flex-wrap: wrap;
  font-size: 12px;
}
.statistics-pagination > span {
  margin-right: auto;
  font-variant-numeric: tabular-nums;
}
@media (max-width: 500px) {
  .statistics-chart-row {
    grid-template-columns: 94px minmax(100px, 1fr);
  }
  .statistics-chart-axis {
    margin-left: 106px;
  }
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
</style>
