import { defineStore } from "pinia";
import { computed, ref } from "vue";
import {
  request,
  type Annotation,
  type Category,
  type ImageItem,
  type ProjectMeta,
} from "../api";

export const useProject = defineStore("project", () => {
  const meta = ref<ProjectMeta | null>(null),
    images = ref<ImageItem[]>([]),
    current = ref<ImageItem | null>(null),
    annotation = ref<Annotation | null>(null);
  const selected = ref<string | null>(null),
    defaultClass = ref<string | null>(null),
    error = ref(""),
    saving = ref(false),
    navigating = ref(false),
    dirty = ref(false);
  const task = ref<"detection" | "segmentation">("segmentation"),
    tool = ref("select"),
    search = ref(""),
    autoSegment = ref(false),
    model = ref("sam2.1_s.pt");
  const history = ref<string[]>([]),
    future = ref<string[]>([]);
  let version = 0,
    savedVersion = 0,
    timer: ReturnType<typeof setTimeout> | undefined,
    flight: Promise<void> | null = null;
  const filtered = computed(() =>
    images.value.filter((i) =>
      i.path.toLowerCase().includes(search.value.toLowerCase()),
    ),
  );
  const object = computed(() =>
    annotation.value?.instances.find((i) => i.id === selected.value),
  );
  function checkpoint() {
    if (annotation.value) {
      history.value.push(JSON.stringify(annotation.value));
      if (history.value.length > 60) history.value.shift();
      future.value = [];
    }
  }
  function changed(geometry: boolean | "detection" | "segmentation" = false) {
    version++;
    dirty.value = true;
    if (geometry && annotation.value) {
      const affected =
        geometry === true
          ? ["detection_review", "segmentation_review"]
          : geometry === "detection"
            ? ["detection_review", "segmentation_review"]
            : ["segmentation_review"];
      for (const key of affected as (
        "detection_review" | "segmentation_review"
      )[]) {
        if (annotation.value[key] === "ok") annotation.value[key] = "pending";
      }
    }
    clearTimeout(timer);
    timer = setTimeout(() => void save().catch(() => {}), 500);
  }
  async function save() {
    clearTimeout(timer);
    if (flight) return flight;
    flight = (async () => {
      saving.value = true;
      try {
        while (savedVersion < version && annotation.value && current.value) {
          const captured = version;
          const updated = await request<Annotation>(
            `/images/${current.value.id}/annotation`,
            "PUT",
            annotation.value,
          );
          annotation.value.revision = updated.revision;
          savedVersion = captured;
        }
        dirty.value = false;
        error.value = "";
      } catch (e) {
        error.value = String(e);
        throw e;
      } finally {
        saving.value = false;
      }
    })();
    try {
      await flight;
    } finally {
      flight = null;
    }
  }
  async function load(image: ImageItem) {
    if (navigating.value) return;
    navigating.value = true;
    try {
      await save();
      const loaded = await request<Annotation>(
        `/images/${image.id}/annotation`,
      );
      await save();
      current.value = image;
      annotation.value = loaded;
      selected.value = null;
      version = savedVersion = 0;
      dirty.value = false;
      history.value = [];
      future.value = [];
      if (
        autoSegment.value &&
        loaded.instances.some((o) => o.box && !o.mask && !o.polygons.length)
      )
        void segment(true);
    } catch (e) {
      error.value = String(e);
    } finally {
      navigating.value = false;
    }
  }
  async function refresh() {
    meta.value = await request<ProjectMeta>("/project");
    const all: ImageItem[] = [];
    for (let offset = 0; ; offset += 1000) {
      const page = await request<{ items: ImageItem[]; total: number }>(
        `/images?offset=${offset}&limit=1000`,
      );
      all.push(...page.items);
      if (all.length >= page.total) break;
    }
    images.value = all;
    if (!meta.value.classes.some((c) => c.id === defaultClass.value))
      defaultClass.value = meta.value.classes[0]?.id ?? null;
  }
  async function open(path: string) {
    try {
      await save();
      await request("/project/open", "POST", { path });
      current.value = null;
      annotation.value = null;
      defaultClass.value = null;
      await refresh();
      if (images.value[0]) await load(images.value[0]);
    } catch (e) {
      error.value = String(e);
    }
  }
  async function addClass(name: string) {
    try {
      const c = await request<Category>("/classes", "POST", { name });
      meta.value?.classes.push(c);
      defaultClass.value = c.id;
      return c;
    } catch (e) {
      error.value = String(e);
    }
  }
  function assign(id: string) {
    if (navigating.value) return;
    if (object.value) {
      checkpoint();
      object.value.class_id = id;
      changed(true);
    } else defaultClass.value = id;
  }
  function remove() {
    if (navigating.value || !object.value || object.value.locked) return;
    checkpoint();
    annotation.value!.instances = annotation.value!.instances.filter(
      (i) => i.id !== selected.value,
    );
    selected.value = null;
    changed(true);
  }
  function undo(redo = false) {
    if (navigating.value || !annotation.value) return;
    const stack = redo ? future.value : history.value,
      other = redo ? history.value : future.value;
    if (!stack.length) return;
    other.push(JSON.stringify(annotation.value));
    const revision = annotation.value.revision;
    annotation.value = JSON.parse(stack.pop()!);
    annotation.value!.revision = revision;
    selected.value = null;
    changed(true);
  }
  function move(delta: number) {
    const index = filtered.value.findIndex((i) => i.id === current.value?.id);
    const next = filtered.value[index + delta];
    if (next) void load(next);
  }
  async function segment(onlyMissing = false, text = "") {
    if (!annotation.value || !current.value) return;
    try {
      await save();
      const imageId = current.value!.id,
        projectId = meta.value?.id,
        editVersion = version;
      const updated = await request<Annotation>(
        `/images/${imageId}/segment`,
        "POST",
        {
          model: model.value,
          instance_id: onlyMissing ? null : selected.value,
          text,
          class_id: defaultClass.value,
        },
      );
      if (current.value?.id !== imageId || meta.value?.id !== projectId) return;
      if (version !== editVersion) {
        error.value =
          "Inference finished after newer edits. Your edits were kept; reload to reconcile.";
        return;
      }
      annotation.value = { ...annotation.value!, ...updated };
      error.value = "";
    } catch (e) {
      error.value = String(e);
    }
  }
  return {
    meta,
    images,
    current,
    annotation,
    selected,
    defaultClass,
    error,
    saving,
    navigating,
    dirty,
    task,
    tool,
    search,
    filtered,
    object,
    history,
    future,
    autoSegment,
    model,
    checkpoint,
    changed,
    save,
    load,
    refresh,
    open,
    addClass,
    assign,
    remove,
    undo,
    move,
    segment,
  };
});
