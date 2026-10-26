import { defineStore } from "pinia";
import { computed, ref, watch, onScopeDispose } from "vue";
import {
  request,
  setProjectSession,
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
    autoSegment = ref(true),
    autoDetect = ref(false),
    detectionModel = ref(""),
    model = ref("");
  const models = ref<ModelsConfig | null>(null);
  watch(() => meta.value?.session, setProjectSession, {
    immediate: true,
    flush: "sync",
  });
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
  const boxPadding = ref({
    box_padding_mode: "pixels" as "pixels" | "ratio",
    box_padding_pixels: 0,
    box_padding_ratio: 0,
    box_padding_min: false,
  });
  function hasCurrentTaskGeometry() {
    return (
      annotation.value?.instances.some((o) =>
        task.value === "detection" ? !!o.box : !!o.mask || !!o.polygons.length,
      ) ?? false
    );
  }
  function setExplicitEmpty(value: boolean) {
    const ann = annotation.value;
    if (!ann || navigating.value) return;
    checkpoint();
    ann.explicit_empty[task.value] = value;
    const key =
      task.value === "detection" ? "detection_review" : "segmentation_review";
    if (!value && ann[key] === "ok" && !hasCurrentTaskGeometry())
      ann[key] = "pending";
    changed();
  }
  function setReview(value: "ok" | "pending" | "uncertain" | "excluded") {
    const ann = annotation.value;
    if (!ann || navigating.value) return;
    if (
      value === "ok" &&
      !hasCurrentTaskGeometry() &&
      !ann.explicit_empty[task.value]
    ) {
      error.value =
        "Add annotations or explicitly confirm no objects before approving this task";
      return;
    }
    checkpoint();
    if (value === "excluded") ann.excluded = !ann.excluded;
    else
      ann[
        task.value === "detection" ? "detection_review" : "segmentation_review"
      ] = value;
    changed();
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
      ...(operation === "boxes_from_masks" ? boxPadding.value : {}),
      model: id,
      operation,
    };
  }
  async function refreshMeta() {
    const projectId = meta.value?.id,
      session = meta.value?.session,
      generation = viewGeneration;
    const updated = await request<ProjectMeta>("/project");
    if (
      updated?.id === projectId &&
      meta.value?.id === projectId &&
      updated.session === session &&
      meta.value?.session === session &&
      generation === viewGeneration
    ) {
      meta.value = updated;
      syncModels();
    }
  }
  async function applyModel(settings: ModelParameters) {
    const projectId = meta.value?.id,
      session = meta.value?.session,
      generation = viewGeneration;
    await save();
    if (generation !== viewGeneration || meta.value?.session !== session)
      return;
    const updated = await request<ProjectMeta>(
      "/model-settings",
      "POST",
      settings,
    );
    if (
      updated.id !== projectId ||
      meta.value?.id !== projectId ||
      updated.session !== session ||
      meta.value?.session !== session
    )
      return;
    meta.value = updated;
    syncModels();
  }
  const history = ref<string[]>([]),
    future = ref<string[]>([]);
  let version = 0,
    savedVersion = 0,
    viewGeneration = 0,
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
  const selectedPrompt = ref<number | "box" | null>(null);
  const selectedGeometry = ref<"box" | "mask" | null>(null);
  const selectionTarget = ref<"results" | "prompts">("results");
  const promptStatus = ref("");
  let promptGeneration = 0,
    promptQueued = false;
  let promptTimer: ReturnType<typeof setTimeout> | undefined;
  function cancelInteractive() {
    promptGeneration++;
    clearTimeout(promptTimer);
    promptQueued = false;
    promptStatus.value = "";
  }
  function activateSelection(target: "results" | "prompts" = "results") {
    if (navigating.value) return;
    tool.value = "select";
    selectionTarget.value = target;
  }
  function selectGeometry(id: string, geometry: "box" | "mask") {
    const obj = annotation.value?.instances.find((o) => o.id === id);
    if (
      !obj ||
      navigating.value ||
      (geometry === "box" ? !obj.box : !(obj.mask || obj.polygons.length))
    )
      return;
    tool.value = "select";
    selectionTarget.value = "results";
    selected.value = id;
    selectedPrompt.value = null;
    selectedGeometry.value = geometry;
  }
  watch(
    selectionTarget,
    () => {
      selectedPrompt.value = null;
      selectedGeometry.value = null;
      cancelInteractive();
    },
    { flush: "sync" },
  );
  function newObject() {
    if (navigating.value || !annotation.value || !current.value) return;
    cancelInteractive();
    cancelCandidates();
    selectionTarget.value = "results";
    selected.value = null;
    selectedPrompt.value = null;
    selectedGeometry.value = null;
    tool.value =
      task.value === "detection"
        ? "box"
        : tool.value === "promptbox"
          ? "promptbox"
          : "positive";
    if (task.value === "segmentation")
      promptStatus.value =
        tool.value === "promptbox"
          ? "Draw a box prompt to start a new object."
          : "Click a foreground point to start a new object.";
  }
  function selectPrompt(id: string, prompt: number | "box") {
    const obj = annotation.value?.instances.find((o) => o.id === id);
    if (
      navigating.value ||
      !obj ||
      (prompt === "box"
        ? !obj.prompt_box
        : !Number.isInteger(prompt) ||
          prompt < 0 ||
          prompt >= obj.points.length)
    )
      return;
    tool.value = "select";
    selectionTarget.value = "prompts";
    selected.value = id;
    selectedGeometry.value = null;
    selectedPrompt.value = prompt;
  }
  function promptsChanged() {
    cancelInteractive();
    if (candidates.value) return; // Candidate mode owns its own regeneration.
    const obj = object.value;
    if (
      !obj ||
      obj.locked ||
      obj.hidden ||
      annotation.value?.excluded ||
      navigating.value
    )
      return;
    if (!(obj.box || obj.prompt_box || obj.points.length)) return;
    promptStatus.value = "Waiting to update mask…";
    promptTimer = setTimeout(() => {
      promptQueued = true;
      void updatePromptMask();
    }, 350);
  }
  async function updatePromptMask() {
    if (candidateFlight || !promptQueued || candidates.value) return;
    promptQueued = false;
    const obj = object.value,
      image = current.value,
      ann = annotation.value;
    if (
      !obj ||
      !image ||
      !ann ||
      obj.locked ||
      obj.hidden ||
      ann.excluded ||
      navigating.value
    )
      return;
    if (!(obj.box || obj.prompt_box || obj.points.length)) return;
    const token = promptGeneration,
      generation = viewGeneration,
      editVersion = version;
    const instanceId = obj.id,
      projectId = meta.value?.id;
    const settings = JSON.stringify(parameters("segmentation"));
    const valid = () =>
      token === promptGeneration &&
      generation === viewGeneration &&
      annotation.value === ann &&
      selected.value === instanceId &&
      current.value?.id === image.id &&
      version === editVersion &&
      !obj.locked &&
      !obj.hidden &&
      !ann.excluded &&
      settings === JSON.stringify(parameters("segmentation")) &&
      !candidates.value;
    candidateFlight = true;
    let accepted = false;
    promptStatus.value = "Updating mask…";
    try {
      await save();
      if (!valid()) return;
      const revision = ann.revision;
      const result = await request<MaskCandidates>(
        `/images/${image.id}/mask-candidates`,
        "POST",
        {
          ...parameters("segmentation"),
          instance_id: instanceId,
          expected_revision: revision,
          project_id: projectId,
          multimask_output: false,
        },
      );
      if (
        !valid() ||
        ann.revision !== revision ||
        result.revision !== revision ||
        result.project_id !== projectId ||
        result.image_id !== image.id ||
        result.instance_id !== instanceId
      )
        return;
      const mask = result.items[0];
      if (!mask)
        throw new Error(
          "No mask returned; existing annotations were preserved",
        );
      checkpoint();
      obj.mask = mask.mask;
      obj.polygons = mask.polygons;
      obj.source = result.model;
      ann.segmentation_review = "pending";
      ann.explicit_empty.segmentation = false;
      changed("segmentation");
      accepted = true;
      await save();
      if (token === promptGeneration) promptStatus.value = "Mask updated";
    } catch (e) {
      if (token === promptGeneration && generation === viewGeneration) {
        error.value = String(e);
        promptStatus.value = accepted
          ? "Mask generated but could not be saved. Your edits were kept; retry saving."
          : "Mask update failed; existing mask was kept. Retry with Refine mask.";
      }
    } finally {
      candidateFlight = false;
      if (token === promptGeneration && promptStatus.value === "Updating mask…")
        promptStatus.value = "";
      if (candidateQueued && candidates.value) {
        candidateQueued = false;
        void generateCandidates(true);
      } else if (promptQueued) void updatePromptMask();
    }
  }
  const canClearImageAnnotations = computed(
    () =>
      !navigating.value &&
      !!current.value &&
      !!annotation.value?.instances.length,
  );
  function clearImageAnnotations(includeLocked = false) {
    const ann = annotation.value;
    if (
      !ann ||
      !canClearImageAnnotations.value ||
      !ann.instances.some((o) => includeLocked || !o.locked)
    )
      return;
    checkpoint();
    cancelInteractive();
    cancelCandidates();
    const remaining = ann.instances.filter((o) => o.locked && !includeLocked);
    if (!remaining.some((o) => o.id === selected.value)) selected.value = null;
    selectedGeometry.value = null;
    selectedPrompt.value = null;
    // Replacing the editing context also invalidates any unfinished canvas gesture.
    annotation.value = {
      ...ann,
      instances: remaining,
      detection_review: "pending",
      segmentation_review: "pending",
      explicit_empty: {
        ...ann.explicit_empty,
        detection: false,
        segmentation: false,
      },
    };
    changed(true);
  }
  const canClearAllPrompts = computed(
    () =>
      !navigating.value &&
      !!current.value &&
      !!annotation.value?.instances.some(
        (o) => !o.locked && (o.points.length || o.prompt_box),
      ),
  );
  function clearAllPrompts() {
    const ann = annotation.value;
    if (!ann || !canClearAllPrompts.value) return;
    checkpoint();
    cancelInteractive();
    cancelCandidates();
    const cleared = new Set<string>();
    for (const obj of ann.instances) {
      if (obj.locked || !(obj.points.length || obj.prompt_box)) continue;
      obj.points = [];
      obj.prompt_box = null;
      cleared.add(obj.id);
    }
    ann.instances = ann.instances.filter(
      (o) => !cleared.has(o.id) || o.box || o.mask || o.polygons.length,
    );
    if (!ann.instances.some((o) => o.id === selected.value))
      selected.value = null;
    selectedPrompt.value = null;
    changed("segmentation");
    promptStatus.value = "All unlocked prompts on this image were cleared.";
  }
  function deletePrompt(clear = false) {
    const obj = object.value;
    if (!obj || obj.locked || navigating.value) return;
    if (!clear && selectedPrompt.value === null) return;
    checkpoint();
    if (clear) {
      obj.points = [];
      obj.prompt_box = null;
    } else if (selectedPrompt.value === "box") obj.prompt_box = null;
    else if (typeof selectedPrompt.value === "number")
      obj.points.splice(selectedPrompt.value, 1);
    selectedPrompt.value = null;
    changed("segmentation");
    if (clear) {
      cancelInteractive();
      cancelCandidates();
    } else promptsChanged();
  }
  watch(
    [
      selected,
      () => meta.value?.session,
      () => meta.value?.id,
      () => meta.value?.root,
      () => current.value?.id,
      tool,
      task,
      () => JSON.stringify(parameters("segmentation")),
      () =>
        JSON.stringify(models.value?.models.find((m) => m.id === model.value)),
      navigating,
    ],
    () => {
      selectedPrompt.value = null;
      selectedGeometry.value = null;
      cancelInteractive();
    },
    { flush: "sync" },
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
    cancelInteractive();
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
      } else if (promptQueued) void updatePromptMask();
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
      projectId = meta.value?.id,
      generation = viewGeneration;
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
      if (
        generation !== viewGeneration ||
        candidates.value !== session ||
        current.value?.id !== imageId ||
        meta.value?.id !== projectId
      )
        return;
      if (version !== captured) {
        error.value =
          "Processing finished after newer edits. Your edits were kept; reload to reconcile.";
        return;
      }
      if (updated.revision < annotation.value!.revision) {
        cancelCandidates();
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
        meta.value?.session,
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
    cancelInteractive();
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
    viewGeneration++;
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
        !loaded.excluded &&
        loaded.segmentation_review === "pending" &&
        !models.value?.missing_dependencies?.length &&
        models.value?.models.some((m) => m.id === model.value && m.available) &&
        loaded.instances.some(
          (o) =>
            !o.locked && !o.hidden && o.box && !o.mask && !o.polygons.length,
        )
      )
        void segment(true);
    } catch (e) {
      error.value = String(e);
    } finally {
      navigating.value = false;
    }
  }
  async function refresh() {
    const generation = viewGeneration,
      session = meta.value?.session;
    const updated = await request<ProjectMeta | null>("/project");
    if (generation !== viewGeneration || meta.value?.session !== session)
      return;
    if (
      updated &&
      meta.value &&
      (updated.session !== meta.value.session ||
        updated.id !== meta.value.id ||
        updated.root !== meta.value.root)
    )
      throw new Error(
        "Project changed in another browser; reopen the intended project",
      );
    meta.value = updated;
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
      if (
        generation !== viewGeneration ||
        meta.value?.session !== updated?.session
      )
        return;
      all.push(...page.items);
      if (all.length >= page.total) break;
    }
    images.value = all;
    syncModels();
    if (!meta.value.classes.some((c) => c.id === defaultClass.value))
      defaultClass.value = meta.value.classes[0]?.id ?? null;
  }
  async function open(path: string) {
    if (navigating.value) return;
    navigating.value = true;
    viewGeneration++;
    cancelCandidates(true);
    try {
      await save();
      await request("/project/open", "POST", { path });
      current.value = null;
      annotation.value = null;
      meta.value = null;
      defaultClass.value = null;
      await refresh();
      navigating.value = false;
      if (images.value[0]) await load(images.value[0]);
    } catch (e) {
      error.value = String(e);
    } finally {
      navigating.value = false;
    }
  }
  async function addClass(name: string) {
    const projectId = meta.value?.id,
      session = meta.value?.session;
    try {
      const c = await request<Category>("/classes", "POST", { name });
      if (meta.value?.id !== projectId || meta.value?.session !== session)
        return;
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
  function deleteSelected() {
    if (selectedPrompt.value !== null) deletePrompt();
    else if (selectedGeometry.value) removeGeometry(selectedGeometry.value);
    else remove();
  }
  function removeGeometry(geometry: "box" | "mask") {
    const obj = object.value,
      ann = annotation.value;
    if (!obj || !ann || obj.locked || navigating.value) return;
    checkpoint();
    cancelInteractive();
    cancelCandidates();
    if (geometry === "box") obj.box = null;
    else {
      obj.mask = null;
      obj.polygons = [];
    }
    if (!(
      obj.box ||
      obj.mask ||
      obj.polygons.length ||
      obj.prompt_box ||
      obj.points.length
    )) {
      ann.instances = ann.instances.filter((o) => o.id !== obj.id);
      selected.value = null;
    }
    selectedGeometry.value = null;
    changed(geometry === "box" ? "detection" : "segmentation");
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
  function editBox(id: string, box: number[], prompt = false, record = true) {
    const ann = annotation.value;
    const obj = ann?.instances.find((o) => o.id === id);
    if (!ann || !obj || obj.locked || navigating.value) return;
    if (box.length !== 4 || !box.every(Number.isFinite)) return;
    const clipped = box.map((v, i) =>
      Math.max(0, Math.min(i % 2 ? ann.height : ann.width, v)),
    );
    if (clipped[2] <= clipped[0] || clipped[3] <= clipped[1]) return;
    const previous = prompt ? obj.prompt_box : obj.box;
    if (JSON.stringify(previous) === JSON.stringify(clipped)) return;
    if (record) checkpoint();
    if (prompt) obj.prompt_box = clipped;
    else {
      obj.box = clipped;
      if (obj.mask || obj.polygons.length)
        ann.segmentation_review = "uncertain";
    }
    changed(prompt ? "segmentation" : "detection");
    if (prompt) promptsChanged();
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
        value.instances
          .filter((o) => o.box)
          .map((o) => [o.id, o.class_id, o.box]),
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
    cancelInteractive();
    if (
      !text &&
      (onlyMissing || !object.value) &&
      !annotation.value.instances.some(
        (o) =>
          !o.locked &&
          !o.hidden &&
          !o.mask &&
          !o.polygons.length &&
          (o.box || o.prompt_box || o.points.length),
      )
    ) {
      promptStatus.value =
        "No missing masks to generate. Select an object to refine, or add a point or box prompt.";
      error.value = "";
      return;
    }
    if (
      !onlyMissing &&
      !text &&
      object.value &&
      !(
        object.value &&
        (object.value.box ||
          object.value.prompt_box ||
          object.value.points.length)
      )
    ) {
      promptStatus.value = "Select an object with points or a box prompt";
      return;
    }
    const generation = viewGeneration;
    try {
      await save();
      if (generation !== viewGeneration || !current.value || !annotation.value)
        return;
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
      if (
        generation !== viewGeneration ||
        current.value?.id !== imageId ||
        meta.value?.id !== projectId
      )
        return;
      if (version !== editVersion) {
        error.value =
          "Inference finished after newer edits. Your edits were kept; reload to reconcile.";
        return;
      }
      if (updated.revision < annotation.value!.revision) return;
      checkpoint();
      annotation.value = { ...annotation.value!, ...updated };
      error.value = "";
    } catch (e) {
      if (generation === viewGeneration) error.value = String(e);
    }
  }
  async function assist(
    operation: "detection" | "boxes_from_masks",
    selected = false,
    recalculate = false,
  ) {
    if (!annotation.value || !current.value) return;
    cancelCandidates();
    const generation = viewGeneration;
    try {
      await save();
      if (generation !== viewGeneration || !current.value || !annotation.value)
        return;
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
      if (
        generation !== viewGeneration ||
        current.value?.id !== imageId ||
        meta.value?.id !== projectId
      )
        return;
      if (version !== captured) {
        error.value =
          "Processing finished after newer edits. Your edits were kept; reload to reconcile.";
        return;
      }
      if (updated.revision < annotation.value!.revision) return;
      checkpoint();
      annotation.value = { ...annotation.value!, ...updated };
      if (operation === "detection") await refreshMeta();
      error.value = "";
    } catch (e) {
      if (generation === viewGeneration) error.value = String(e);
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
      captured = version,
      generation = viewGeneration;
    const updated = await request<Annotation>(`/images/${imageId}/annotation`);
    if (
      current.value?.id === imageId &&
      generation === viewGeneration &&
      meta.value?.id === projectId &&
      version === captured &&
      updated.revision >= annotation.value!.revision &&
      !dirty.value
    )
      annotation.value = updated;
  }
  function applyCategory(category: Category) {
    const current = [
      ...(meta.value?.classes ?? []),
      ...(meta.value?.tags ?? []),
    ].find((entry) => entry.id === category.id);
    if (current) Object.assign(current, category);
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
    selectedPrompt,
    selectedGeometry,
    selectionTarget,
    activateSelection,
    selectGeometry,
    newObject,
    removeGeometry,
    selectPrompt,
    promptsChanged,
    promptStatus,
    deletePrompt,
    clearAllPrompts,
    clearImageAnnotations,
    canClearImageAnnotations,
    canClearAllPrompts,
    deleteSelected,
    history,
    future,
    autoSegment,
    autoDetect,
    setReview,
    setExplicitEmpty,
    detectionModel,
    parameters,
    boxPadding,
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
    applyCategory,
    assign,
    remove,
    editBox,
    undo,
    move,
    segment,
  };
});
