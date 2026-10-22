import { defineStore } from "pinia";
import { computed, ref, watch, onScopeDispose } from "vue";
import {
  request,
  type Annotation,
  type Category,
  type ImageItem,
  type ProjectMeta,
  type ModelsConfig,
  type Operation,
  type ModelParameters,
  type MaskCandidates,
} from "../api";

export const useProject = defineStore("project", () => {
  const meta = ref<ProjectMeta | null>(null),
    images = ref<ImageItem[]>([]),
    current = ref<ImageItem | null>(null),
    annotation = ref<Annotation | null>(null);
  const selected = ref<string | null>(null),
    defaultClass = ref<string | null>(null),
    classPickerOpen = ref(false),
    error = ref(""),
    saving = ref(false),
    navigating = ref(false),
    dirty = ref(false);
  const task = ref<"detection" | "segmentation">("segmentation"),
    tool = ref("select"),
    search = ref(""),
    autoSegment = ref(false),
    autoDetect = ref(false),
    detectionModel = ref(""),
    model = ref("");
  const models = ref<ModelsConfig | null>(null);
  async function refreshModels() {
    try {
      models.value = await request<ModelsConfig>("/models");
      if (!models.value.models.some((m) => m.id === model.value))
        model.value = models.value.default_model;
      if (
        !models.value.models.some(
          (m) => m.id === detectionModel.value && m.task === "detection",
        )
      )
        detectionModel.value = models.value.default_detection_model || "";
      syncModels();
    } catch (e) {
      error.value = String(e);
    }
  }
  function syncModels() {
    if (
      meta.value?.active_models?.segmentation &&
      models.value?.models.some(
        (m) => m.id === meta.value?.active_models?.segmentation,
      )
    )
      model.value = meta.value.active_models.segmentation;
    if (
      meta.value?.active_models?.detection &&
      models.value?.models.some(
        (m) => m.id === meta.value?.active_models?.detection,
      )
    )
      detectionModel.value = meta.value.active_models.detection;
  }
  function parameters(
    operation: Operation,
    selectedModel?: string,
  ): ModelParameters {
    const id =
      selectedModel ??
      (operation === "detection" ? detectionModel.value : model.value);
    return {
      confidence: 0.25,
      iou: 0.7,
      imgsz: 640,
      max_det: 300,
      model_classes: null,
      allow_new_classes: false,
      write_policy: "fill_empty",
      device_type: "auto",
      devices: "auto",
      ...meta.value?.model_settings?.[id],
      model: id,
      operation,
    };
  }
  async function refreshMeta() {
    const projectId = meta.value?.id;
    const updated = await request<ProjectMeta>("/project");
    if (updated?.id === projectId) {
      meta.value = updated;
      syncModels();
    }
  }
  async function applyModel(settings: ModelParameters) {
    await save();
    const projectId = meta.value?.id;
    const updated = await request<ProjectMeta>(
      "/model-settings",
      "POST",
      settings,
    );
    if (updated.id !== projectId || meta.value?.id !== projectId) return;
    meta.value = updated;
    syncModels();
  }
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
  interface CandidateSession {
    phase: "loading" | "ready" | "error" | "applying";
    response: MaskCandidates | null;
    active: number;
    error: string;
    promptKey: string;
    annotationKey: string;
  }
  const candidates = ref<CandidateSession | null>(null),
    candidateNotice = ref("");
  let candidateGeneration = 0,
    candidateFlight = false,
    candidateQueued = false;
  let candidateTimer: ReturnType<typeof setTimeout> | undefined;
  let candidateNoticeTimer: ReturnType<typeof setTimeout> | undefined;
  const canGenerateCandidates = computed(
    () =>
      !!(
        object.value &&
        !object.value.locked &&
        !object.value.hidden &&
        !annotation.value?.excluded &&
        (object.value.box ||
          object.value.prompt_box ||
          object.value.points.length) &&
        tool.value !== "text" &&
        models.value?.models.some(
          (m) => m.id === model.value && m.available && m.mask_candidates,
        )
      ),
  );
  const candidate = computed(
    () => candidates.value?.response?.items[candidates.value.active],
  );
  function promptKey() {
    const obj = object.value;
    return JSON.stringify(obj && [obj.box, obj.prompt_box, obj.points]);
  }
  function annotationKey() {
    return JSON.stringify({ ...annotation.value, revision: 0 });
  }
  function cancelCandidates(notify = false) {
    if (notify && candidates.value) {
      candidateNotice.value =
        "Candidate preview discarded; the original annotation was kept.";
      clearTimeout(candidateNoticeTimer);
      candidateNoticeTimer = setTimeout(() => {
        candidateNotice.value = "";
      }, 5000);
    }
    candidateGeneration++;
    clearTimeout(candidateTimer);
    candidateQueued = false;
    candidates.value = null;
  }
  async function generateCandidates(regenerate = false) {
    if (
      !canGenerateCandidates.value ||
      !current.value ||
      !annotation.value ||
      !object.value
    )
      return;
    if (!regenerate || !candidates.value) {
      cancelCandidates();
      candidates.value = {
        phase: "loading",
        response: null,
        active: 0,
        error: "",
        promptKey: promptKey(),
        annotationKey: annotationKey(),
      };
    }
    if (candidateFlight) {
      candidateQueued = true;
      return;
    }
    const session = candidates.value!;
    const token = ++candidateGeneration;
    const imageId = current.value.id,
      projectId = meta.value?.id,
      instanceId = object.value.id;
    session.phase = "loading";
    session.response = null;
    session.error = "";
    candidateFlight = true;
    try {
      await save();
      if (candidateGeneration !== token || candidates.value !== session) return;
      const revision = annotation.value!.revision;
      const result = await request<MaskCandidates>(
        `/images/${imageId}/mask-candidates`,
        "POST",
        {
          ...parameters("segmentation"),
          instance_id: instanceId,
          expected_revision: revision,
          project_id: projectId,
        },
      );
      if (
        candidateGeneration !== token ||
        current.value?.id !== imageId ||
        meta.value?.id !== projectId ||
        selected.value !== instanceId
      )
        return;
      if (
        result.revision !== annotation.value?.revision ||
        result.project_id !== projectId ||
        result.image_id !== imageId ||
        result.instance_id !== instanceId ||
        !result.items.length
      ) {
        throw new Error("The annotation changed; generate candidates again.");
      }
      session.response = result;
      session.active = 0;
      session.phase = "ready";
    } catch (e) {
      if (candidateGeneration === token && candidates.value === session) {
        session.phase = "error";
        session.error = String(e);
      }
    } finally {
      candidateFlight = false;
      if (candidateQueued && candidates.value) {
        candidateQueued = false;
        void generateCandidates(true);
      }
    }
  }
  async function applyCandidate() {
    const session = candidates.value,
      preview = session?.response,
      chosen = candidate.value;
    if (
      !preview ||
      !chosen ||
      session?.phase !== "ready" ||
      !current.value ||
      !annotation.value
    )
      return;
    const imageId = current.value.id,
      projectId = meta.value?.id;
    session.phase = "applying";
    try {
      await save();
      if (candidates.value !== session) return;
      if (annotation.value?.revision !== preview.revision)
        throw new Error("The annotation changed; generate candidates again.");
      const captured = version;
      const updated = await request<Annotation>(
        `/images/${imageId}/mask-candidates/apply`,
        "POST",
        {
          project_id: preview.project_id,
          instance_id: preview.instance_id,
          revision: preview.revision,
          image_stamp: preview.image_stamp,
          model: preview.model,
          mask: chosen.mask,
        },
      );
      if (current.value?.id !== imageId || meta.value?.id !== projectId) return;
      if (version !== captured) {
        error.value =
          "Processing finished after newer edits. Your edits were kept; reload to reconcile.";
        return;
      }
      checkpoint();
      cancelCandidates();
      annotation.value = { ...annotation.value!, ...updated };
      error.value = "";
    } catch (e) {
      if (candidates.value === session) {
        session.phase = "error";
        session.response = null;
        session.error = String(e);
      }
    }
  }
  watch(
    () =>
      JSON.stringify([
        current.value?.id,
        meta.value?.id,
        selected.value,
        task.value,
        JSON.stringify(parameters("segmentation")),
        JSON.stringify(meta.value?.classes),
        JSON.stringify(models.value?.models.find((m) => m.id === model.value)),
        tool.value === "text",
      ]),
    () => cancelCandidates(),
    { flush: "sync" },
  );
  watch(
    () => (candidates.value ? annotationKey() : ""),
    (key) => {
      const session = candidates.value;
      if (!session || key === session.annotationKey) return;
      if (
        promptKey() !== session.promptKey &&
        canGenerateCandidates.value &&
        session.phase !== "applying"
      ) {
        session.promptKey = promptKey();
        session.annotationKey = key;
        session.phase = "loading";
        session.response = null;
        session.error = "";
        candidateGeneration++;
        candidateQueued = false;
        clearTimeout(candidateTimer);
        candidateTimer = setTimeout(() => void generateCandidates(true), 500);
      } else cancelCandidates();
    },
    { flush: "pre" },
  );
  watch(
    () => annotation.value?.revision,
    (revision) => {
      if (
        candidates.value?.phase === "ready" &&
        candidates.value.response?.revision !== revision
      )
        cancelCandidates();
    },
    { flush: "sync" },
  );
  onScopeDispose(() => {
    clearTimeout(candidateTimer);
    clearTimeout(candidateNoticeTimer);
    cancelCandidates();
  });
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
            ? ["detection_review"]
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
    cancelCandidates(true);
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
        task.value === "detection" &&
        autoDetect.value &&
        loaded.detection_review === "pending" &&
        !loaded.excluded &&
        !loaded.instances.length &&
        detectionModel.value
      )
        void detect();
      if (
        task.value === "segmentation" &&
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
    meta.value = await request<ProjectMeta | null>("/project");
    if (!meta.value) {
      images.value = [];
      current.value = null;
      annotation.value = null;
      return;
    }
    const all: ImageItem[] = [];
    for (let offset = 0; ; offset += 1000) {
      const page = await request<{ items: ImageItem[]; total: number }>(
        `/images?offset=${offset}&limit=1000`,
      );
      all.push(...page.items);
      if (all.length >= page.total) break;
    }
    images.value = all;
    syncModels();
    if (!meta.value.classes.some((c) => c.id === defaultClass.value))
      defaultClass.value = meta.value.classes[0]?.id ?? null;
  }
  async function open(path: string) {
    cancelCandidates(true);
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
  function openClassPicker() {
    if (!object.value || navigating.value) return;
    if (object.value.locked) {
      error.value = "Unlock this annotation before changing its class.";
      return;
    }
    classPickerOpen.value = true;
  }
  function assign(id: string) {
    if (navigating.value || object.value?.locked) return;
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
    const before = taskGeometry(annotation.value);
    other.push(JSON.stringify(annotation.value));
    const revision = annotation.value.revision;
    annotation.value = JSON.parse(stack.pop()!);
    annotation.value!.revision = revision;
    selected.value = null;
    const after = taskGeometry(annotation.value!);
    const detectionChanged = before[0] !== after[0],
      segmentationChanged = before[1] !== after[1];
    changed(
      detectionChanged && segmentationChanged
        ? true
        : detectionChanged
          ? "detection"
          : segmentationChanged
            ? "segmentation"
            : false,
    );
  }
  function taskGeometry(value: Annotation) {
    return [
      JSON.stringify([
        value.excluded,
        value.instances.map((o) => [o.id, o.class_id, o.box]),
      ]),
      JSON.stringify([
        value.excluded,
        value.instances.map((o) => [
          o.id,
          o.class_id,
          o.mask,
          o.polygons,
          o.prompt_box,
          o.points,
        ]),
      ]),
    ];
  }
  function move(delta: number) {
    const index = filtered.value.findIndex((i) => i.id === current.value?.id);
    const next = filtered.value[index + delta];
    if (next) void load(next);
  }
  async function segment(onlyMissing = false, text = "") {
    cancelCandidates();
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
          ...parameters("segmentation"),
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
  async function assist(
    operation: "detection" | "boxes_from_masks",
    selected = false,
    recalculate = false,
  ) {
    if (!annotation.value || !current.value) return;
    cancelCandidates();
    try {
      await save();
      const imageId = current.value!.id,
        projectId = meta.value?.id,
        captured = version;
      const updated = await request<Annotation>(
        `/images/${imageId}/${operation === "detection" ? "detect" : "boxes-from-masks"}`,
        "POST",
        {
          ...parameters(operation),
          model: operation === "detection" ? detectionModel.value : "",
          instance_id: selected ? selectedValue() : null,
          recalculate_boxes: recalculate,
        },
      );
      if (current.value?.id !== imageId || meta.value?.id !== projectId) return;
      if (version !== captured) {
        error.value =
          "Processing finished after newer edits. Your edits were kept; reload to reconcile.";
        return;
      }
      checkpoint();
      annotation.value = { ...annotation.value!, ...updated };
      if (operation === "detection") await refreshMeta();
      error.value = "";
    } catch (e) {
      error.value = String(e);
    }
  }
  function selectedValue() {
    return selected.value;
  }
  function detect() {
    return assist("detection");
  }
  function boxesFromMasks(selected = false, recalculate = false) {
    return assist("boxes_from_masks", selected, recalculate);
  }
  async function refreshCurrent() {
    if (!current.value || dirty.value || navigating.value) return;
    const imageId = current.value.id,
      projectId = meta.value?.id,
      captured = version;
    const updated = await request<Annotation>(`/images/${imageId}/annotation`);
    if (
      current.value?.id === imageId &&
      meta.value?.id === projectId &&
      version === captured &&
      !dirty.value
    )
      annotation.value = updated;
  }
  return {
    candidates,
    candidate,
    candidateNotice,
    canGenerateCandidates,
    generateCandidates,
    cancelCandidates,
    applyCandidate,
    meta,
    images,
    current,
    annotation,
    selected,
    defaultClass,
    classPickerOpen,
    openClassPicker,
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
    autoDetect,
    detectionModel,
    parameters,
    refreshMeta,
    applyModel,
    refreshCurrent,
    detect,
    boxesFromMasks,
    model,
    models,
    refreshModels,
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
