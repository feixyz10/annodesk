/** English source messages are the fallback; project data and diagnostics stay untouched. */
import { ref, watch } from "vue";
import chinese from "./locales/zh-CN.json";
import { readPreference, writePreference } from "./preferences";
export type Locale = "en" | "zh-CN";
export const localeStorageKey = "annodesk.locale";
export const messages: Record<string, string> = chinese;
export function resolveLocale(value: unknown): Locale {
  return value === "zh-CN" ? "zh-CN" : "en";
}
export const locale = ref<Locale>(
  resolveLocale(readPreference(localeStorageKey)),
);
export function setLocale(value: unknown) {
  locale.value = resolveLocale(value);
}
watch(
  locale,
  (value) => {
    if (typeof document !== "undefined") document.documentElement.lang = value;
    writePreference(localeStorageKey, value);
  },
  { immediate: true, flush: "sync" },
);
export function t(
  source: string,
  values: Record<string, string | number> = {},
): string {
  const message =
    locale.value === "zh-CN" && Object.hasOwn(messages, source)
      ? messages[source]
      : source;
  return message.replace(/\{(\w+)\}/g, (match, key: string) =>
    Object.hasOwn(values, key) ? String(values[key]) : match,
  );
}
export function uiError(source: string): string {
  const key = source.replace(/^Error: /, "");
  return Object.hasOwn(messages, key) ? t(key) : source;
}
const taskNames: Record<string, string> = {
  detection: "Detection",
  segmentation: "Segmentation",
  boxes_from_masks: "Boxes from masks",
  export: "Export",
};
const statusNames: Record<string, string> = {
  pending: "Not reviewed",
  ok: "Approved",
  uncertain: "Needs review",
  excluded: "Excluded",
  running: "Running",
  complete: "Complete",
  failed: "Failed",
  cancelled: "Cancelled",
  interrupted: "Interrupted",
  preflight: "Scanning annotations…",
  preparing: "Preparing…",
  loading: "Loading models…",
  packaging: "Writing export metadata…",
  stopped: "Stopped",
  fill_empty: "Empty images only",
  append: "Append with duplicate checks",
  equal: "Identical classes",
  model_subset: "Model is a subset",
  project_subset: "Project is a subset",
};
const toolNames: Record<string, string> = {
  select: "Select",
  box: "Draw box",
  positive: "Positive point",
  negative: "Negative point",
  promptbox: "Box prompt: mask only",
  text: "Text prompt (SAM 3)",
  pan: "Pan",
};
export const taskLabel = (value: string) => t(taskNames[value] ?? value);
export const statusLabel = (value: string) => t(statusNames[value] ?? value);
export const toolLabel = (value: string) => t(toolNames[value] ?? value);
export function formatDate(value: number): string {
  return new Date(value * 1000).toLocaleString(
    locale.value === "zh-CN" ? "zh-CN" : "en-US",
  );
}
export function formatTime(value: string): string {
  return new Date(value).toLocaleTimeString(
    locale.value === "zh-CN" ? "zh-CN" : "en-US",
    { hour12: false },
  );
}
