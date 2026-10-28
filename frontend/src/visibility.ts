import { computed, ref, watch } from "vue";
import type { Instance } from "./api";
import { readPreference, writePreference } from "./preferences";

export type LayerKind = "box" | "mask" | "prompts";
export const layerKinds: LayerKind[] = ["box", "mask", "prompts"];
export const layerNames: Record<LayerKind, string> = {
  box: "Detection boxes",
  mask: "Segmentation masks",
  prompts: "SAM prompts",
};
export function hasLayerGeometry(obj: Instance, kind: LayerKind): boolean {
  if (kind === "box") return !!obj.box;
  if (kind === "mask") return !!(obj.mask || obj.polygons.length);
  return !!(obj.prompt_box || obj.points.length);
}
type Flags = Record<LayerKind, boolean>;
type ImageView = {
  imageHidden: boolean;
  layers: Flags;
  objects: Record<string, Flags>;
  hidden: Record<string, boolean>;
};
const all = (): Flags => ({ box: true, mask: true, prompts: true });
function flags(value: unknown, fallback = all()): Flags {
  const source = value as Partial<Flags> | null;
  return Object.fromEntries(
    layerKinds.map((k) => [
      k,
      typeof source?.[k] === "boolean" ? source[k] : fallback[k],
    ]),
  ) as Flags;
}
function read(key: string): unknown {
  try {
    return JSON.parse(readPreference(key) || "null");
  } catch {
    return null;
  }
}
export function createVisibility(
  context: () => {
    project: string;
    image?: string;
    instances: Instance[];
  },
) {
  const globalLayers = ref(all());
  const imageView = ref<ImageView>({
    imageHidden: false,
    layers: all(),
    objects: {},
    hidden: {},
  });
  // Keep in-memory fallback when browser persistence is unavailable.
  const memory = new Map<string, string>();
  const projectKey = computed(() => `annodesk.layers:${context().project}`);
  const imageKey = computed(
    () => `${projectKey.value}:${context().image ?? ""}`,
  );
  function stored(key: string) {
    try {
      return memory.has(key) ? JSON.parse(memory.get(key)!) : read(key);
    } catch {
      return null;
    }
  }
  function persist(key: string, value: unknown) {
    const json = JSON.stringify(value);
    memory.set(key, json);
    writePreference(key, json);
  }
  watch(
    projectKey,
    (key) => {
      globalLayers.value = flags(stored(key));
    },
    { immediate: true, flush: "sync" },
  );
  watch(
    imageKey,
    (key) => {
      const saved = stored(key) as Partial<ImageView> | null;
      const objects: Record<string, Flags> = {};
      if (saved?.objects && typeof saved.objects === "object")
        for (const [id, value] of Object.entries(saved.objects))
          objects[id] = flags(value);
      const hidden = Object.fromEntries(
        Object.entries(saved?.hidden ?? {}).filter(
          ([, value]) => typeof value === "boolean",
        ),
      );
      imageView.value = {
        imageHidden: saved?.imageHidden === true,
        layers: flags(saved?.layers),
        objects,
        hidden,
      };
    },
    { immediate: true, flush: "sync" },
  );
  // Read old view gates as local choices. Every edit flattens them into per-geometry
  // flags, so bulk hiding never prevents a child from being shown independently.
  function objectLayers(obj: Instance): Flags {
    const own = imageView.value.objects[obj.id] ?? all();
    const hidden =
      imageView.value.imageHidden ||
      (imageView.value.hidden[obj.id] ?? obj.hidden);
    return Object.fromEntries(
      layerKinds.map((k) => [
        k,
        !hidden && imageView.value.layers[k] && own[k],
      ]),
    ) as Flags;
  }
  function layerVisible(obj: Instance, kind: LayerKind) {
    return globalLayers.value[kind] && objectLayers(obj)[kind];
  }
  function objectHidden(obj: Instance) {
    return !layerKinds.some(
      (k) => hasLayerGeometry(obj, k) && layerVisible(obj, k),
    );
  }
  const imageHasVisibleGeometry = computed(() =>
    context().instances.some((o) => !objectHidden(o)),
  );
  function setLocalVisibility(
    targets: Instance[],
    kinds: LayerKind[],
    visible: boolean,
  ) {
    if (!context().image) return;
    const objects = Object.fromEntries(
      context().instances.map((o) => [o.id, objectLayers(o)]),
    );
    for (const obj of targets)
      for (const kind of kinds) objects[obj.id][kind] = visible;
    imageView.value = {
      imageHidden: false,
      layers: all(),
      hidden: Object.fromEntries(context().instances.map((o) => [o.id, false])),
      objects,
    };
    persist(imageKey.value, imageView.value);
  }
  function setObjectHidden(id: string, hidden: boolean) {
    const obj = context().instances.find((o) => o.id === id);
    if (obj) setLocalVisibility([obj], layerKinds, !hidden);
  }
  function setImageHidden(hidden: boolean) {
    setLocalVisibility(context().instances, layerKinds, !hidden);
  }
  function layerBlock(obj: Instance | undefined, kind: LayerKind) {
    if (!globalLayers.value[kind]) return "Hidden globally";
    if (obj && !objectLayers(obj)[kind]) return "Hidden for this object";
    return "";
  }
  function setLayer(
    scope: "global" | "image" | string,
    kind: LayerKind,
    value: boolean,
  ) {
    if (scope === "global") {
      globalLayers.value = { ...globalLayers.value, [kind]: value };
      persist(projectKey.value, globalLayers.value);
    } else {
      const targets =
        scope === "image"
          ? context().instances
          : context().instances.filter((o) => o.id === scope);
      setLocalVisibility(targets, [kind], value);
    }
  }
  function imageLayerState(kind: LayerKind): "all" | "mixed" | "none" {
    const objects = context().instances.filter((o) =>
      hasLayerGeometry(o, kind),
    );
    const visible = objects.filter((o) => layerVisible(o, kind)).length;
    return !visible ? "none" : visible === objects.length ? "all" : "mixed";
  }
  function toggleImageLayer(kind: LayerKind) {
    if (!context().image || !globalLayers.value[kind]) return;
    setLayer("image", kind, imageLayerState(kind) !== "all");
  }
  function applyView(preset: "detection" | "segmentation" | "all") {
    globalLayers.value = {
      box: preset !== "segmentation",
      mask: preset !== "detection",
      prompts: preset !== "detection",
    };
    persist(projectKey.value, globalLayers.value);
  }
  function resetImageLayers() {
    imageView.value = {
      imageHidden: false,
      layers: all(),
      hidden: Object.fromEntries(context().instances.map((o) => [o.id, false])),
      objects: Object.fromEntries(
        context().instances.map((o) => [o.id, all()]),
      ),
    };
    persist(imageKey.value, imageView.value);
  }
  return {
    globalLayers,
    imageView,
    objectLayers,
    objectHidden,
    imageHasVisibleGeometry,
    setObjectHidden,
    setImageHidden,
    layerVisible,
    layerBlock,
    setLayer,
    imageLayerState,
    toggleImageLayer,
    applyView,
    resetImageLayers,
  };
}
