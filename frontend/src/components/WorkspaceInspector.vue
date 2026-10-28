<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from "vue";
import { NDropdown, type DropdownOption } from "naive-ui";
import { t, taskLabel } from "../i18n";
import { useProject } from "../stores/project";
import { readPreference, writePreference } from "../preferences";
import SelectedObjectActions from "./SelectedObjectActions.vue";
import type { Instance } from "../api";
import {
  hasLayerGeometry,
  layerKinds,
  layerNames,
  type LayerKind,
} from "../visibility";
import Icon from "./Icon.vue";
const store = useProject();
const query = ref("");
const expanded = ref<string | null>(null);
const container = ref<HTMLElement>();
const list = ref<HTMLElement>();
const saved = Number(readPreference("annodesk-instance-list-height"));
const split = ref(saved >= 25 && saved <= 75 ? saved : 55);
const menu = ref<{
  id: string;
  image: string | undefined;
  session: string | undefined;
  x: number;
  y: number;
} | null>(null);
const objects = computed(() =>
  (store.annotation?.instances ?? []).filter((o, index) => {
    const name =
      store.meta?.classes.find((c) => c.id === o.class_id)?.name ??
      t("Unassigned");
    return `${index + 1} ${name}`
      .toLowerCase()
      .includes(query.value.trim().toLowerCase());
  }),
);
function name(id: string | null) {
  return store.meta?.classes.find((c) => c.id === id)?.name ?? t("Unassigned");
}
async function reveal() {
  await nextTick();
  const entry = [
    ...(list.value?.querySelectorAll<HTMLElement>(".inspector-object-entry") ??
      []),
  ].find((el) => el.dataset.objectId === store.selected);
  const row = entry?.querySelector<HTMLElement>(".inspector-object-row");
  if (!row || !list.value) return;
  const r = row.getBoundingClientRect(),
    bounds = list.value.getBoundingClientRect();
  const top =
    bounds.top +
    (list.value
      .querySelector(".object-column-headings")
      ?.getBoundingClientRect().height ?? 0);
  if (
    expanded.value === store.selected &&
    entry &&
    entry.getBoundingClientRect().bottom > bounds.bottom
  )
    list.value.scrollTop += r.top - top;
  else if (r.top < top) list.value.scrollTop += r.top - top;
  else if (r.bottom > bounds.bottom)
    list.value.scrollTop += r.bottom - bounds.bottom;
}
watch(
  () => [store.selected, store.selectedGeometry, store.selectedPrompt],
  () => {
    menu.value = null;
    if (expanded.value !== store.selected) expanded.value = null;
    void reveal();
  },
);
watch(
  [() => store.current?.id, () => store.meta?.id, () => store.meta?.session],
  () => {
    query.value = "";
    expanded.value = null;
    menu.value = null;
  },
);
watch(query, () => {
  menu.value = null;
  if (list.value) list.value.scrollTop = 0;
});
function select(id: string) {
  store.selectObjectRow(id);
  if (expanded.value !== id) expanded.value = null;
  void reveal();
}
function geometry(id: string, kind: "box" | "mask" | "prompts") {
  if (kind === "prompts") {
    const obj = store.annotation?.instances.find((o) => o.id === id);
    if (obj) store.selectPrompt(id, obj.prompt_box ? "box" : 0);
  } else store.selectGeometry(id, kind);
  if (expanded.value !== id) expanded.value = null;
  void reveal();
}
const layerIcons = { box: "box", mask: "mask", prompts: "promptbox" };
const missingLabels = {
  box: "No detection box",
  mask: "No mask",
  prompts: "No SAM prompts",
};
function toggleDisabled(obj: Instance, kind: LayerKind) {
  return (
    store.navigating ||
    !hasLayerGeometry(obj, kind) ||
    !store.globalLayers[kind]
  );
}
function toggleLabel(obj: Instance, kind: LayerKind) {
  if (!hasLayerGeometry(obj, kind)) return t(missingLabels[kind]);
  const action = t(
    store.layerVisible(obj, kind) ? "Hide {layer}" : "Show {layer}",
    { layer: t(layerNames[kind]) },
  );
  const block = !store.globalLayers[kind]
    ? t("Show this layer in global Layers first")
    : "";
  return block ? `${action} · ${block}` : action;
}
function toggleGeometry(obj: Instance, kind: LayerKind) {
  if (!toggleDisabled(obj, kind))
    store.setLayer(obj.id, kind, !store.objectLayers(obj)[kind]);
}
function headingDisabled(kind: LayerKind) {
  return (
    store.navigating ||
    !store.globalLayers[kind] ||
    !store.annotation?.instances.some((o) => hasLayerGeometry(o, kind))
  );
}
function headingLabel(kind: LayerKind) {
  const action = t(
    store.imageLayerState(kind) === "all"
      ? "Hide all {layer} on this image"
      : "Show all {layer} on this image",
    { layer: t(layerNames[kind]) },
  );
  return !store.globalLayers[kind]
    ? `${action} · ${t("Show this layer in global Layers first")}`
    : action;
}
function selectedGeometry(obj: Instance, kind: LayerKind) {
  return (
    store.selected === obj.id &&
    (kind === "prompts"
      ? store.selectedPrompt !== null
      : store.selectedGeometry === kind)
  );
}
function toggleLock(id: string) {
  if (store.navigating) return;
  const obj = store.annotation?.instances.find((o) => o.id === id);
  if (!obj) return;
  store.checkpoint();
  obj.locked = !obj.locked;
  store.changed();
}

function disclosure(id: string) {
  if (expanded.value === id && store.selected === id) expanded.value = null;
  else {
    if (store.selected !== id) select(id);
    expanded.value = id;
    void reveal();
  }
}
async function openMenu(event: MouseEvent, id: string) {
  if (store.navigating) return;
  // Bind the menu to the row context; never apply an open menu after navigation.
  if (store.selected !== id) select(id);
  const rect = (
    event.currentTarget as HTMLElement | null
  )?.getBoundingClientRect();
  const annotation = store.annotation,
    image = store.current?.id,
    session = store.meta?.session;
  const x = event.clientX || rect?.right || 0,
    y = event.clientY || rect?.bottom || 0;
  await nextTick();
  if (
    store.selected !== id ||
    store.annotation !== annotation ||
    store.current?.id !== image ||
    store.meta?.session !== session
  )
    return;
  menu.value = { id, image, session, x, y };
}
const menuOptions = computed<DropdownOption[]>(() => {
  const obj = store.object;
  if (!obj) return [];
  const blocked = obj.locked || store.navigating;
  const prompts = !!(obj.box || obj.prompt_box || obj.points.length);
  return [
    ...layerKinds.map((kind) => ({
      key: `select-${kind}`,
      label: t(
        {
          box: "Select detection box",
          mask: "Select mask",
          prompts: "Select prompts",
        }[kind],
      ),
      disabled:
        store.navigating ||
        !hasLayerGeometry(obj, kind) ||
        !store.layerVisible(obj, kind),
    })),
    { key: "separator-selection", type: "divider" },
    { key: "class", label: t("Change class"), disabled: blocked },
    {
      key: "refine",
      label: t("Refine mask"),
      disabled:
        blocked ||
        store.task !== "segmentation" ||
        store.annotation?.excluded ||
        !prompts,
    },
    {
      key: "candidates",
      label: t("Generate candidates"),
      disabled: !store.canGenerateCandidates || !!store.candidates,
    },
    {
      key: "box",
      label: t(obj.box ? "Recalculate box from mask" : "Create box from mask"),
      disabled: blocked || !(obj.mask || obj.polygons.length),
    },
    {
      key: "clear",
      label: t("Clear prompts"),
      disabled: blocked || !(obj.prompt_box || obj.points.length),
    },
    { key: "separator", type: "divider" },
    {
      key: "delete-box",
      label: t("Delete box only"),
      disabled: blocked || !obj.box,
    },
    {
      key: "delete-mask",
      label: t("Delete mask only"),
      disabled: blocked || !(obj.mask || obj.polygons.length),
    },
    {
      key: "delete-prompt",
      label: t("Delete prompt"),
      disabled: blocked || store.selectedPrompt === null,
    },
    { key: "separator-delete", type: "divider" },
    { key: "delete-object", label: t("Delete object"), disabled: blocked },
  ];
});
function menuAction(key: string) {
  const context = menu.value;
  if (
    !context ||
    context.id !== store.selected ||
    context.image !== store.current?.id ||
    context.session !== store.meta?.session ||
    !menuOptions.value.some(
      (o) => o.key === key && !o.disabled && o.type !== "divider",
    )
  )
    return;
  menu.value = null;
  if (key === "select-box" || key === "select-mask" || key === "select-prompts")
    geometry(context.id, key.slice(7) as LayerKind);
  else if (key === "class") store.openClassPicker();
  else if (key === "refine") void store.segment();
  else if (key === "candidates") void store.generateCandidates();
  else if (key === "box") store.boxConversion = "selected";
  else if (key === "clear") store.deletePrompt(true);
  else if (key === "delete-box") store.removeGeometry("box");
  else if (key === "delete-mask") store.removeGeometry("mask");
  else if (key === "delete-prompt") store.deletePrompt();
  else if (key === "delete-object") store.remove();
}
function setSplit(value: number) {
  split.value = Math.max(25, Math.min(75, value));
}
function saveSplit() {
  writePreference("annodesk-instance-list-height", String(split.value));
}
let cleanup = () => {};
function resize(event: PointerEvent) {
  event.preventDefault();
  cleanup();
  const bounds = container.value?.getBoundingClientRect();
  if (!bounds) return;
  const move = (e: PointerEvent) =>
    setSplit(((e.clientY - bounds.top) / bounds.height) * 100);
  const stop = () => {
    window.removeEventListener("pointermove", move);
    window.removeEventListener("pointerup", stop);
    window.removeEventListener("pointercancel", stop);
    saveSplit();
  };
  cleanup = stop;
  window.addEventListener("pointermove", move);
  window.addEventListener("pointerup", stop);
  window.addEventListener("pointercancel", stop);
}
onBeforeUnmount(() => cleanup());
</script>
<template>
  <div
    ref="container"
    class="workspace-inspector"
    :style="{ '--object-list-height': split + '%' }"
  >
    <div class="inspector-task-switch" role="group" :aria-label="t('Task')">
      <button
        v-for="task in ['detection', 'segmentation'] as const"
        :key="task"
        :aria-pressed="store.task === task"
        @click="store.task = task"
      >
        {{ taskLabel(task) }}
      </button>
    </div>
    <section class="inspector-objects" :aria-label="t('Objects')">
      <div class="inspector-list-header">
        <strong
          >{{ t("Objects") }}
          <span class="muted">{{
            store.annotation?.instances.length ?? 0
          }}</span></strong
        ><button
          :disabled="!store.current || store.navigating"
          :title="t('Keep this annotation and start the next object · N')"
          @click="store.newObject()"
        >
          {{ t("New object") }} <kbd>N</kbd>
        </button>
      </div>
      <div class="inspector-object-content">
        <slot name="actions" />
        <input
          v-model="query"
          type="search"
          :aria-label="t('Search objects')"
          :placeholder="t('Search objects…')"
        />
        <div ref="list" class="inspector-object-list">
          <div class="object-column-headings">
            <span>{{ t("Class") }}</span>
            <button
              v-for="kind in layerKinds"
              :key="kind"
              class="layer-heading"
              :data-layer-heading="kind"
              :class="{
                'hidden-geometry': store.imageLayerState(kind) === 'none',
              }"
              :disabled="headingDisabled(kind)"
              :title="headingLabel(kind)"
              :aria-label="headingLabel(kind)"
              :aria-pressed="
                store.imageLayerState(kind) === 'mixed'
                  ? 'mixed'
                  : store.imageLayerState(kind) === 'all'
              "
              @click="!headingDisabled(kind) && store.toggleImageLayer(kind)"
            >
              <Icon
                :name="layerIcons[kind]"
                :slashed="store.imageLayerState(kind) === 'none'"
              />
            </button>
            <button
              class="layer-heading"
              data-layer-heading="visibility"
              :class="{ 'visibility-hidden': !store.imageHasVisibleGeometry }"
              :disabled="!store.current || store.navigating"
              :title="
                t(
                  !store.imageHasVisibleGeometry
                    ? 'Show annotations on this image'
                    : 'Hide all annotations on this image',
                )
              "
              :aria-label="
                t(
                  !store.imageHasVisibleGeometry
                    ? 'Show annotations on this image'
                    : 'Hide all annotations on this image',
                )
              "
              :aria-pressed="store.imageHasVisibleGeometry"
              @click="store.setImageHidden(store.imageHasVisibleGeometry)"
            >
              <Icon :name="!store.imageHasVisibleGeometry ? 'eyeoff' : 'eye'" />
            </button>
            <span :title="t('Locked')"><Icon name="lock" /></span>
            <span :title="t('More object actions')"><Icon name="more" /></span
            ><span></span>
          </div>

          <div
            v-for="object in objects"
            :key="object.id"
            class="inspector-object-entry"
            :data-object-id="object.id"
          >
            <div
              class="inspector-object-row"
              :class="{
                active: store.selected === object.id,
                'hover-preview': store.hovered?.id === object.id,
              }"
              @contextmenu.prevent="openMenu($event, object.id)"
            >
              <button
                class="object-name"
                :title="t('Select object; double-click to toggle details')"
                :aria-pressed="store.selected === object.id"
                @click="select(object.id)"
                @dblclick="disclosure(object.id)"
              >
                <small class="object-index">{{
                  (store.annotation?.instances.findIndex(
                    (o) => o.id === object.id,
                  ) ?? -1) + 1
                }}</small
                ><i
                  :style="{
                    background:
                      store.meta?.classes.find((c) => c.id === object.class_id)
                        ?.color ?? '#888',
                  }"
                ></i
                ><span>{{ name(object.class_id) }}</span>
              </button>
              <button
                v-for="kind in layerKinds"
                :key="kind"
                :data-column="kind"
                class="geometry-visibility"
                :disabled="toggleDisabled(object, kind)"
                :class="{
                  'missing-geometry': !hasLayerGeometry(object, kind),
                  'hidden-geometry':
                    hasLayerGeometry(object, kind) &&
                    !store.layerVisible(object, kind),
                  'geometry-selected': selectedGeometry(object, kind),
                  'hover-preview':
                    store.hovered?.id === object.id &&
                    (kind === 'prompts'
                      ? ['point', 'prompt_box'].includes(store.hovered.kind)
                      : store.hovered.kind === kind),
                }"
                :title="toggleLabel(object, kind)"
                :aria-label="toggleLabel(object, kind)"
                :aria-pressed="
                  hasLayerGeometry(object, kind) &&
                  store.layerVisible(object, kind)
                "
                @click="toggleGeometry(object, kind)"
              >
                <Icon
                  v-if="hasLayerGeometry(object, kind)"
                  :name="layerIcons[kind]"
                  :slashed="!store.layerVisible(object, kind)"
                />
                <span v-else aria-hidden="true">—</span>
                <span
                  v-if="selectedGeometry(object, kind)"
                  class="geometry-selection-dot"
                  :aria-label="t('Selected geometry')"
                ></span>
              </button>
              <button
                data-column="visibility"
                :class="{ 'visibility-hidden': store.objectHidden(object) }"
                :disabled="store.navigating"
                :aria-label="
                  t(store.objectHidden(object) ? 'Show object' : 'Hide object')
                "
                :title="
                  t(store.objectHidden(object) ? 'Show object' : 'Hide object')
                "
                :aria-pressed="!store.objectHidden(object)"
                @click="
                  store.setObjectHidden(object.id, !store.objectHidden(object))
                "
              >
                <Icon :name="store.objectHidden(object) ? 'eyeoff' : 'eye'" />
              </button>
              <button
                data-column="lock"
                :title="t(object.locked ? 'Unlock object' : 'Lock object')"
                :aria-label="t(object.locked ? 'Unlock object' : 'Lock object')"
                :aria-pressed="object.locked"
                @click="toggleLock(object.id)"
              >
                <Icon :name="object.locked ? 'lock' : 'unlock'" />
              </button>
              <button
                data-column="more"
                :title="t('More object actions')"
                :aria-label="t('More object actions')"
                :aria-expanded="menu?.id === object.id"
                aria-haspopup="menu"
                @click="openMenu($event, object.id)"
              >
                <Icon name="more" />
              </button>
              <button
                class="object-disclosure"
                :title="
                  t(
                    expanded === object.id
                      ? 'Collapse object details'
                      : 'Expand object details',
                  )
                "
                :aria-label="
                  t(
                    expanded === object.id
                      ? 'Collapse object details'
                      : 'Expand object details',
                  )
                "
                :aria-expanded="expanded === object.id"
                :aria-controls="'object-details-' + object.id"
                @click="disclosure(object.id)"
              >
                <Icon
                  :name="expanded === object.id ? 'chevronup' : 'chevrondown'"
                />
              </button>
            </div>
            <div
              v-if="expanded === object.id && store.selected === object.id"
              :id="'object-details-' + object.id"
              class="inline-object-details"
            >
              <SelectedObjectActions />
            </div>
          </div>
          <p v-if="!objects.length" class="muted inspector-list-empty">
            {{ query ? t("No matching objects") : t("No objects yet") }}
          </p>
        </div>
      </div>
    </section>
    <div
      class="horizontal split inspector-divider"
      role="separator"
      tabindex="0"
      :aria-label="t('Resize objects and image properties')"
      aria-orientation="horizontal"
      :aria-valuenow="Math.round(split)"
      :aria-valuemin="25"
      :aria-valuemax="75"
      @pointerdown="resize"
      @keydown.up.prevent.stop="
        setSplit(split - 5);
        saveSplit();
      "
      @keydown.down.prevent.stop="
        setSplit(split + 5);
        saveSplit();
      "
      @dblclick="
        split = 55;
        saveSplit();
      "
    ></div>
    <section class="inspector-properties" :aria-label="t('Image properties')">
      <div class="image-properties-heading">
        <strong>{{ t("Image properties") }}</strong>
      </div>
      <div
        id="image-properties"
        class="inspector-property-content inspector-image-properties"
      >
        <p class="muted image-path" :title="store.current?.path">
          {{ store.current?.path ?? t("No image selected") }}
        </p>
        <slot name="image" />
      </div>
    </section>
    <NDropdown
      v-if="menu"
      :menu-props="() => ({ class: 'annodesk-object-menu' })"
      trigger="manual"
      :show="!!menu"
      :x="menu?.x"
      :y="menu?.y"
      :options="menuOptions"
      placement="bottom-end"
      @select="menuAction"
      @clickoutside="menu = null"
      @update:show="
        (value) => {
          if (!value) menu = null;
        }
      "
    />
  </div>
</template>
