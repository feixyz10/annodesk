<script setup lang="ts">
import { t, uiError, formatTime } from "../i18n";
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import { NModal } from "naive-ui";
import { apiBase, request } from "../api";
import { useProject } from "../stores/project";
const props = defineProps<{ show: boolean }>();
const emit = defineEmits<{ "update:show": [boolean] }>();
const store = useProject();
const autoScroll = ref(true);
interface LogRecord {
  session_id: string;
  sequence: number;
  timestamp: string;
  level_name: string;
  level_no: number;
  message: string;
  truncated: boolean;
}
interface Page {
  items: LogRecord[];
  next_cursor: string;
  gap: boolean;
  session_id: string;
}
const rows = ref<LogRecord[]>([]),
  level = ref(20),
  comparison = ref("gte"),
  scope = ref(store.meta ? "project" : "service"),
  paused = ref(false),
  gap = ref(false),
  error = ref(""),
  scroll = ref(0),
  viewport = ref<HTMLElement>();
let stream: EventSource | undefined,
  cursor = "",
  generation = 0;
let scopeInitialized = false;
let retryTimer: ReturnType<typeof setTimeout> | undefined;
let clearedAt = "";
const visibleRows = computed(() => {
  const start = Math.max(0, Math.floor(scroll.value / 72) - 2);
  return rows.value
    .slice(start, start + 35)
    .map((row, index) => ({ row, top: (start + index) * 72 }));
});
function query() {
  const params = new URLSearchParams({
    level: String(level.value),
    comparison: comparison.value,
  });
  if (scope.value === "project" && store.meta)
    params.set("project_id", store.meta.id);
  return params;
}
function append(page: Page) {
  if (cursor && !cursor.startsWith(page.session_id + ":")) {
    rows.value = [];
    scroll.value = 0;
    clearedAt = "";
  }
  gap.value ||= page.gap;
  const seen = new Set(rows.value.map((r) => r.session_id + ":" + r.sequence));
  const previousTop = viewport.value?.scrollTop || 0;
  const atBottom =
    !viewport.value ||
    viewport.value.scrollHeight - previousTop - viewport.value.clientHeight <
      80;
  const merged = [
    ...rows.value,
    ...page.items.filter(
      (r) =>
        !seen.has(r.session_id + ":" + r.sequence) &&
        (!clearedAt.startsWith(r.session_id + ":") ||
          r.sequence > Number(clearedAt.split(":")[1])),
    ),
  ];
  const dropped = Math.max(0, merged.length - 1000);
  rows.value = merged.slice(-1000);
  cursor = page.next_cursor;
  if (atBottom && autoScroll.value) {
    void nextTick(() => {
      if (viewport.value)
        viewport.value.scrollTop = viewport.value.scrollHeight;
    });
  } else if (dropped) {
    scroll.value = Math.max(0, previousTop - dropped * 72);
    void nextTick(() => {
      if (viewport.value) viewport.value.scrollTop = scroll.value;
    });
  }
}
async function connect(reset = false) {
  const token = ++generation;
  if (retryTimer) clearTimeout(retryTimer);
  stream?.close();
  stream = undefined;
  if (reset) {
    rows.value = [];
    cursor = "";
    clearedAt = "";
    gap.value = false;
    scroll.value = 0;
  }
  if (!props.show || paused.value) return;
  try {
    const params = query();
    if (cursor) params.set("cursor", cursor);
    appendIfCurrent(await request<Page>("/logs?" + params), token);
    if (token !== generation) return;
    params.set("cursor", cursor);
    stream = new EventSource(apiBase + "/logs/stream?" + params);
    stream.onmessage = (event) => {
      if (token === generation) {
        append(JSON.parse(event.data));
        error.value = "";
      }
    };
    stream.onerror = () => {
      if (token !== generation) return;
      error.value = "Disconnected. Reconnecting…";
      stream?.close();
      stream = undefined;
      retryTimer = setTimeout(() => void connect(), 1500);
    };
  } catch (e) {
    if (token === generation) {
      error.value = String(e);
      retryTimer = setTimeout(() => void connect(), 3000);
    }
  }
}
function appendIfCurrent(page: Page, token: number) {
  if (generation === token) {
    append(page);
    error.value = "";
  }
}
function clearView() {
  clearedAt = cursor;
  void connect();
  rows.value = [];
  scroll.value = 0;
}
async function copy() {
  try {
    await navigator.clipboard.writeText(
      rows.value
        .map((r) => `${r.timestamp} | ${r.level_name} | ${r.message}`)
        .join("\n"),
    );
  } catch {
    error.value = "Clipboard unavailable; select and copy the log text.";
  }
}
watch(
  () => props.show,
  () => {
    if (props.show && !scopeInitialized) {
      scope.value = store.meta ? "project" : "service";
      scopeInitialized = true;
    }
    void connect();
  },
);
watch(
  [level, comparison, scope, () => store.meta?.id],
  () => void connect(true),
);
watch(paused, () => void connect());
onBeforeUnmount(() => {
  generation++;
  if (retryTimer) clearTimeout(retryTimer);
  stream?.close();
});
</script>
<template>
  <NModal
    :show="show"
    @update:show="emit('update:show', $event)"
    preset="card"
    :title="t('Logs')"
    style="
      width: 960px;
      max-width: 92vw;
      max-height: 85vh;
      overflow: hidden;
      resize: both;
    "
    content-style="overflow:auto;min-height:0"
  >
    <div class="log-controls">
      <select v-model="scope" :aria-label="t('Log scope')">
        <option value="service">{{ t("Service") }}</option>
        <option value="project" :disabled="!store.meta">
          {{ t("Current project") }}
        </option>
      </select>
      <select v-model="comparison" :aria-label="t('Level comparison')">
        <option value="gte">≥</option>
        <option value="eq">=</option>
      </select>
      <select v-model="level" :aria-label="t('Log level')">
        <option
          v-for="item in [
            [20, 'INFO'],
            [25, 'SUCCESS'],
            [30, 'WARNING'],
            [40, 'ERROR'],
            [50, 'CRITICAL'],
          ]"
          :value="item[0]"
        >
          {{ item[1] }}
        </option>
      </select>
      <button @click="paused = !paused">
        {{ paused ? t("Resume") : t("Pause") }}</button
      ><button @click="clearView">{{ t("Clear view") }}</button
      ><button @click="copy">{{ t("Copy") }}</button>
      <label
        ><input v-model="autoScroll" type="checkbox" />
        {{ t("Auto-scroll") }}</label
      >
      <a
        :href="apiBase + '/logs/download'"
        download
        :title="t('Download the current backend log file')"
        >{{ t("Download") }}</a
      >
    </div>
    <p class="muted">
      {{ t("Current backend session ·") }} {{ rows.length
      }}{{
        t(
          "/1000 events. Independent CLI sessions are available in their log files.",
        )
      }}
    </p>
    <p v-if="gap" role="status">
      {{ t("Some earlier events are no longer available.") }}
    </p>
    <p v-if="error" role="status">
      {{ uiError(error) }}
      <button @click="connect()">{{ t("Retry") }}</button>
    </p>
    <div
      ref="viewport"
      class="log-viewport"
      @scroll="scroll = ($event.target as HTMLElement).scrollTop"
      role="log"
      :aria-label="t('Important service events')"
    >
      <p v-if="!rows.length" class="muted">
        {{ paused ? t("Paused") : t("No matching events yet") }}
      </p>
      <div :style="{ height: rows.length * 72 + 'px', position: 'relative' }">
        <div
          v-for="item in visibleRows"
          :key="item.row.session_id + item.row.sequence"
          class="log-row"
          :style="{ top: item.top + 'px' }"
        >
          <time :title="item.row.timestamp">{{
            formatTime(item.row.timestamp)
          }}</time>
          <b :class="'level-' + item.row.level_name.toLowerCase()">{{
            item.row.level_name
          }}</b>
          <span :title="item.row.message"
            >{{ item.row.message
            }}{{ item.row.truncated ? t("… [see file]") : "" }}</span
          >
        </div>
      </div>
    </div>
  </NModal>
</template>
<style scoped>
.log-controls {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  align-items: center;
}
.log-controls a {
  color: var(--accent);
}
.log-viewport {
  height: min(55vh, 600px);
  min-height: 160px;
  overflow: auto;
  border-top: 1px solid var(--line);
}
.log-row {
  position: absolute;
  height: 72px;
  width: 100%;
  display: grid;
  grid-template-columns: 72px 76px 1fr;
  gap: 8px;
  align-items: start;
  padding: 12px 0;
  border-bottom: 1px solid var(--line);
  font-size: 11px;
  font-family: ui-monospace, monospace;
}
.log-row span {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
time {
  color: #788398;
}
.level-error,
.level-critical {
  color: #b34e5d;
}
.level-warning {
  color: #ad711b;
}
.level-success {
  color: #24835d;
}
</style>
