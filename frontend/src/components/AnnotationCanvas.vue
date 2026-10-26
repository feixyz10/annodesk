<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch, computed } from "vue";
import Konva from "konva";
import { toolCursors } from "../toolCursors";
import { maskOutline } from "../maskOutline";
import { useProject } from "../stores/project";
import { projectResource, instance, type Annotation } from "../api";
const store = useProject(),
  host = ref<HTMLDivElement>(),
  ratio = ref(1);
const spaceHeld = ref(false),
  panning = ref(false);
const cursor = computed(() => {
  if (store.navigating) return "wait";
  if (spaceHeld.value || store.tool === "pan")
    return panning.value ? "grabbing" : "grab";
  if (store.tool === "select")
    return store.selectionTarget === "prompts"
      ? toolCursors.prompts
      : "default";
  return toolCursors[store.tool] ?? "default";
});
let stage: Konva.Stage,
  layer: Konva.Layer,
  background: HTMLImageElement | null = null,
  observer: ResizeObserver,
  temporary: Konva.Rect | null = null,
  start: { x: number; y: number } | null = null,
  space = false,
  transformer: Konva.Transformer;
let gestureGeneration = 0;
let drawingContext: {
  generation: number;
  annotation: Annotation;
  tool: string;
} | null = null;
function isTransformHandle(target: Konva.Node) {
  let node: Konva.Node | null = target;
  while (node && node !== stage) {
    if (node === transformer) return true;
    node = node.getParent?.() ?? null;
  }
  return false;
}
function cancelDrawing() {
  start = null;
  drawingContext = null;
  const shape = temporary;
  temporary = null;
  shape?.destroy();
  layer?.batchDraw();
}
function invalidateGestures() {
  gestureGeneration++;
  cancelDrawing();
}
function validContext(generation: number, annotation: Annotation) {
  return (
    generation === gestureGeneration &&
    store.annotation === annotation &&
    !store.navigating &&
    !space
  );
}
const maskCache = new Map<string, HTMLImageElement>(),
  loadingMasks = new Set<string>();
const maskHitCache = new Map<
  string,
  { width: number; height: number; alpha: Uint8Array }
>();
let outlineCache: { key: string; image: HTMLCanvasElement } | null = null;
function drawSelectionOutline() {
  const obj = store.object,
    ann = store.annotation;
  if (store.candidate && store.candidates?.response?.instance_id === obj?.id) {
    outlineCache = null;
    return;
  }
  if (
    !obj?.mask ||
    !ann ||
    obj.hidden ||
    store.selectedGeometry === "box" ||
    store.selectedPrompt !== null
  ) {
    outlineCache = null;
    return;
  }
  const color =
    store.meta?.classes.find((c) => c.id === obj.class_id)?.color ?? "#657286";
  const key = overlayKey(obj.id, ann.revision, color);
  const pixels = maskHitCache.get(key);
  if (!pixels) return;
  const scale = stage.scaleX();
  const cacheKey = JSON.stringify([
    key,
    Math.max(1, Math.min(8, Math.ceil(2 / Math.max(scale, 0.01)))),
  ]);
  if (outlineCache?.key !== cacheKey) {
    const image = document.createElement("canvas");
    image.width = pixels.width;
    image.height = pixels.height;
    const ctx = image.getContext("2d");
    if (!ctx) return;
    const data = ctx.createImageData(pixels.width, pixels.height);
    data.data.set(
      maskOutline(pixels.alpha, pixels.width, pixels.height, scale),
    );
    ctx.putImageData(data, 0, 0);
    outlineCache = { key: cacheKey, image };
  }
  layer.add(
    new Konva.Image({
      image: outlineCache.image,
      width: ann.width,
      height: ann.height,
      listening: false,
    }),
  );
}
function overlayKey(id: string, revision: number, color: string) {
  return JSON.stringify([
    store.meta?.session ?? store.meta?.id,
    store.current?.id,
    id,
    revision,
    color,
  ]);
}
function insidePolygon(p: { x: number; y: number }, points: number[][]) {
  let inside = false;
  for (let i = 0, j = points.length - 1; i < points.length; j = i++) {
    const [x, y] = points[i],
      [px, py] = points[j];
    if (y > p.y !== py > p.y && p.x < ((px - x) * (p.y - y)) / (py - y) + x)
      inside = !inside;
  }
  return inside;
}
function selectMaskAt(p: { x: number; y: number }) {
  const ann = store.annotation;
  if (!ann) return;
  for (const obj of [...ann.instances].reverse()) {
    if (obj.hidden) continue;
    let hit = false;
    if (obj.mask) {
      const color =
        store.meta?.classes.find((c) => c.id === obj.class_id)?.color ??
        "#657286";
      const pixels = maskHitCache.get(overlayKey(obj.id, ann.revision, color));
      const x = Math.floor(p.x),
        y = Math.floor(p.y);
      hit = !!(
        pixels &&
        x >= 0 &&
        y >= 0 &&
        x < pixels.width &&
        y < pixels.height &&
        pixels.alpha[y * pixels.width + x]
      );
    } else hit = obj.polygons.some((poly) => insidePolygon(p, poly));
    if (hit) {
      selectObject(obj.id);
      store.selectedGeometry = "mask";
      return;
    }
  }
  store.selected = null;
  store.selectedPrompt = null;
  store.selectedGeometry = null;
}
let fitted = true;
let imageGeneration = 0;
let candidateImage: HTMLImageElement | null = null;
let candidateImageKey = "";
let lastSelection = { id: "", time: 0 };
function selectObject(id: string) {
  if (space || store.tool !== "select") return;
  const now = performance.now();
  const twice = lastSelection.id === id && now - lastSelection.time < 350;
  lastSelection = { id, time: twice ? 0 : now };
  store.selected = id;
  store.selectedPrompt = null;
  if (twice) store.openClassPicker();
}
function fit() {
  if (!stage || !store.annotation || stage.width() <= 0 || stage.height() <= 0)
    return;
  fitted = true;
  const a = store.annotation;
  const scale =
    Math.min(stage.width() / a.width, stage.height() / a.height) * 0.94;
  stage.scale({ x: scale, y: scale });
  stage.position({
    x: (stage.width() - a.width * scale) / 2,
    y: (stage.height() - a.height * scale) / 2,
  });
  ratio.value = scale;
  draw();
}
function zoom(factor: number, at?: { x: number; y: number }) {
  if (!stage) return;
  fitted = false;
  const point = at ?? { x: stage.width() / 2, y: stage.height() / 2 },
    old = stage.scaleX(),
    scale = Math.max(0.05, Math.min(32, old * factor));
  const world = {
    x: (point.x - stage.x()) / old,
    y: (point.y - stage.y()) / old,
  };
  stage.scale({ x: scale, y: scale });
  stage.position({
    x: point.x - world.x * scale,
    y: point.y - world.y * scale,
  });
  ratio.value = scale;
  draw();
}
function coordinates() {
  const p = stage.getPointerPosition()!;
  return stage.getAbsoluteTransform().copy().invert().point(p);
}
function draw() {
  if (!layer) return;
  layer.destroyChildren();
  if (!store.annotation) {
    maskCache.clear();
    maskHitCache.clear();
    outlineCache = null;
    return;
  }
  const a = store.annotation,
    generation = gestureGeneration;
  const liveKeys = new Set(
    a.instances
      .filter((o) => o.mask && !o.hidden)
      .map((o) =>
        JSON.stringify([
          store.meta?.session ?? store.meta?.id,
          store.current?.id,
          o.id,
          a.revision,
          store.meta?.classes.find((c) => c.id === o.class_id)?.color ??
            "#657286",
        ]),
      ),
  );
  for (const key of maskCache.keys()) {
    if (!liveKeys.has(key)) {
      maskCache.delete(key);
      maskHitCache.delete(key);
    }
  }
  if (background)
    layer.add(
      new Konva.Image({
        image: background,
        width: a.width,
        height: a.height,
        listening: false,
      }),
    );
  for (const object of a.instances) {
    if (object.hidden) continue;
    const color =
      store.meta?.classes.find((c) => c.id === object.class_id)?.color ??
      "#657286";
    const previewing = !!(
      store.candidate && store.candidates?.response?.instance_id === object.id
    );
    if (previewing && candidateImage)
      layer.add(
        new Konva.Image({
          image: candidateImage,
          width: a.width,
          height: a.height,
          listening: false,
        }),
      );
    if (!previewing && object.mask && store.current) {
      const imageId = store.current.id,
        projectId = store.meta?.session ?? store.meta?.id,
        revision = a.revision,
        generation = imageGeneration,
        key = JSON.stringify([projectId, imageId, object.id, revision, color]);
      const cached = maskCache.get(key);
      if (cached)
        layer.add(
          new Konva.Image({
            image: cached,
            width: a.width,
            height: a.height,
            listening: false,
          }),
        );
      else if (!store.dirty && !loadingMasks.has(key)) {
        loadingMasks.add(key);
        const im = new Image();
        im.crossOrigin = "anonymous";
        im.src = projectResource(
          `/images/${imageId}/masks/${object.id}?revision=${a.revision}&color=${encodeURIComponent(color)}`,
        );
        im.onload = () => {
          if (generation !== imageGeneration) return;
          loadingMasks.delete(key);
          if (
            store.current?.id === imageId &&
            (store.meta?.session ?? store.meta?.id) === projectId &&
            store.annotation?.revision === revision
          ) {
            const canvas = document.createElement("canvas");
            canvas.width = a.width;
            canvas.height = a.height;
            const context = canvas.getContext("2d", {
              willReadFrequently: true,
            });
            if (context) {
              try {
                context.drawImage(im, 0, 0, a.width, a.height);
                const rgba = context.getImageData(0, 0, a.width, a.height).data;
                const alpha = new Uint8Array(a.width * a.height);
                for (let i = 0; i < alpha.length; i++)
                  alpha[i] = rgba[i * 4 + 3];
                maskHitCache.set(key, {
                  width: a.width,
                  height: a.height,
                  alpha,
                });
              } catch {
                store.error =
                  "Could not prepare mask selection; reload the image.";
              }
            }
            maskCache.set(key, im);
            draw();
          }
        };
        im.onerror = () => {
          if (generation !== imageGeneration) return;
          loadingMasks.delete(key);
          if (
            store.current?.id === imageId &&
            (store.meta?.session ?? store.meta?.id) === projectId &&
            store.annotation?.revision === revision &&
            !store.dirty
          )
            store.error = "Could not load lossless mask overlay";
        };
      }
    }
    for (const points of previewing
      ? store.candidate!.polygons
      : object.polygons) {
      const shape = new Konva.Line({
        points: points.flat(),
        closed: true,
        fill: object.mask || previewing ? "rgba(0,0,0,0.001)" : color + "55",
        stroke: color,
        strokeWidth:
          store.selected === object.id && store.selectedGeometry === "mask"
            ? 2.5
            : 1.5,
        strokeScaleEnabled: false,
        listening: false,
      });
      // Stage selection tests lossless alpha, including holes and disconnected regions.

      layer.add(shape);
    }
    for (const kind of ["box", "prompt_box"] as const) {
      const box = object[kind];
      if (!box) continue;
      const isPrompt = kind === "prompt_box";
      const selectable =
        store.selectionTarget === (isPrompt ? "prompts" : "results");
      const focused =
        store.selected === object.id &&
        (isPrompt
          ? store.selectedPrompt === "box"
          : store.selectedGeometry === "box");
      const shape = new Konva.Rect({
        x: box[0],
        y: box[1],
        width: box[2] - box[0],
        height: box[3] - box[1],
        // Konva's hit canvas fills paths unless fillEnabled is explicitly disabled.
        fillEnabled: false,
        hitStrokeWidth: 8,
        stroke: isPrompt ? "#a86a0a" : color,
        strokeWidth: focused ? 2.5 : 1.5,
        strokeScaleEnabled: false,
        dash: isPrompt ? [7, 4] : [],
        listening: !space && store.tool === "select" && selectable,
        draggable:
          !space && store.tool === "select" && selectable && !object.locked,
      });
      shape.on("mousedown touchstart", (e) => {
        if (
          validContext(generation, a) &&
          store.tool === "select" &&
          selectable
        ) {
          e.cancelBubble = true;
          if (isPrompt) store.selectPrompt(object.id, "box");
          else {
            selectObject(object.id);
            store.selectedGeometry = "box";
          }
        }
      });
      shape.on("dragstart", () => {
        if (validContext(generation, a) && selectable && !object.locked)
          store.checkpoint();
      });
      shape.on("dragend", () => {
        if (
          !validContext(generation, a) ||
          store.tool !== "select" ||
          !selectable ||
          object.locked
        )
          return;
        const w = shape.width(),
          h = shape.height(),
          x = Math.max(0, Math.min(a.width - w, shape.x())),
          y = Math.max(0, Math.min(a.height - h, shape.y()));
        store.editBox(object.id, [x, y, x + w, y + h], isPrompt, false);
        draw();
      });
      shape.on("transformstart", () => {
        if (validContext(generation, a) && selectable && !object.locked)
          store.checkpoint();
      });
      shape.on("transformend", () => {
        if (
          !validContext(generation, a) ||
          store.tool !== "select" ||
          !selectable ||
          object.locked
        )
          return;
        const x = Math.max(0, shape.x()),
          y = Math.max(0, shape.y()),
          w = Math.max(
            1,
            Math.min(a.width - x, shape.width() * shape.scaleX()),
          ),
          h = Math.max(
            1,
            Math.min(a.height - y, shape.height() * shape.scaleY()),
          );
        store.editBox(object.id, [x, y, x + w, y + h], isPrompt, false);
        draw();
      });
      layer.add(shape);
      if (
        !space &&
        selectable &&
        focused &&
        !object.locked &&
        store.tool === "select"
      ) {
        transformer = new Konva.Transformer({
          nodes: [shape],
          rotateEnabled: false,
          keepRatio: false,
          flipEnabled: false,
          ignoreStroke: true,
          anchorSize: 7,
          anchorStroke: isPrompt ? "#a86a0a" : "#315fe9",
          anchorFill: "#fff",
          borderEnabled: false,
        });
        layer.add(transformer);
      }
    }
    object.points.forEach((p, index) => {
      const selected =
        store.selected === object.id && store.selectedPrompt === index;
      const point = new Konva.Circle({
        x: p.x,
        y: p.y,
        radius: (selected ? 6 : 4) / stage.scaleX(),
        fill: p.positive ? "#24835d" : "#c14d5c",
        stroke: selected ? "#172d4d" : "white",
        strokeWidth: (selected ? 2 : 1) / stage.scaleX(),
        listening:
          !space &&
          store.tool === "select" &&
          store.selectionTarget === "prompts",
      });
      point.on("mousedown touchstart", (e) => {
        if (
          validContext(generation, a) &&
          store.tool === "select" &&
          store.selectionTarget === "prompts"
        ) {
          e.cancelBubble = true;
          store.selectPrompt(object.id, index);
        }
      });
      layer.add(point);
    });
  }
  drawSelectionOutline();
  layer.batchDraw();
}
function key(e: KeyboardEvent) {
  if (
    e.isComposing ||
    e.ctrlKey ||
    e.metaKey ||
    e.altKey ||
    (e.target as HTMLElement).closest(
      "input,textarea,select,button,.n-modal,[role=dialog],[contenteditable=true],.mask-candidates,.statistics-drawer",
    )
  )
    return;
  if (e.code === "Space") {
    e.preventDefault();
    if (!space) {
      invalidateGestures();
      space = true;
      spaceHeld.value = true;
      stage?.draggable(true);
      draw();
    }
  }
}
function release(e: KeyboardEvent) {
  if (e.code === "Space") {
    space = false;
    spaceHeld.value = false;
    panning.value = false;
    stage?.draggable(store.tool === "pan");
    draw();
  }
}
function blur() {
  space = false;
  spaceHeld.value = false;
  panning.value = false;
  invalidateGestures();
  stage?.draggable(store.tool === "pan");
  draw();
}
onMounted(() => {
  stage = new Konva.Stage({
    container: host.value!,
    width: host.value!.clientWidth,
    height: host.value!.clientHeight,
  });
  layer = new Konva.Layer();
  stage.add(layer);
  observer = new ResizeObserver(() => {
    const previous = stage.size();
    const width = host.value!.clientWidth,
      height = host.value!.clientHeight;
    stage.size({ width, height });
    if (fitted) fit();
    else {
      // Keep the same world point at the view center when panels resize.
      stage.position({
        x: stage.x() + (width - previous.width) / 2,
        y: stage.y() + (height - previous.height) / 2,
      });
      draw();
    }
  });
  stage.on("dragstart", (event) => {
    if (event.target === stage) panning.value = true;
  });
  stage.on("dragend", (event) => {
    if (event.target === stage) {
      fitted = false;
      panning.value = false;
    }
  });
  observer.observe(host.value!);
  window.addEventListener("blur", blur);
  stage.on("wheel", (e) => {
    e.evt.preventDefault();
    zoom(Math.exp(-e.evt.deltaY * 0.002), stage.getPointerPosition()!);
  });
  stage.on("mousedown touchstart", (e) => {
    // Transformer anchors own resizing. Never reinterpret them as mask/background selection.
    if (isTransformHandle(e.target)) return;
    if (!store.annotation || store.navigating || space || store.tool === "pan")
      return;
    const p = coordinates(),
      a = store.annotation;
    if (p.x < 0 || p.y < 0 || p.x > a.width || p.y > a.height) return;
    if (["box", "promptbox"].includes(store.tool)) {
      cancelDrawing();
      start = p;
      drawingContext = {
        generation: gestureGeneration,
        annotation: a,
        tool: store.tool,
      };
      temporary = new Konva.Rect({
        x: p.x,
        y: p.y,
        width: 1,
        height: 1,
        stroke: store.tool === "promptbox" ? "#a86a0a" : "#315fe9",
        dash: store.tool === "promptbox" ? [7, 4] : [],
        strokeWidth: 1.5,
        strokeScaleEnabled: false,
      });
      layer.add(temporary);
    } else if (["positive", "negative"].includes(store.tool)) {
      if (store.object?.locked) return;
      store.checkpoint();
      let obj = store.object;
      if (!obj) {
        obj = instance(store.defaultClass);
        a.instances.push(obj);
        store.selected = obj.id;
      }
      obj.points.push({ x: p.x, y: p.y, positive: store.tool === "positive" });
      store.changed("segmentation");
      store.promptsChanged();
    } else if (store.tool === "select") {
      if (store.selectionTarget === "results") selectMaskAt(p);
      else {
        store.selected = null;
        store.selectedPrompt = null;
        store.selectedGeometry = null;
      }
    }
  });
  stage.on("mousemove touchmove", () => {
    if (!start || !temporary || !drawingContext) return;
    if (!validContext(drawingContext.generation, drawingContext.annotation)) {
      cancelDrawing();
      return;
    }
    const p = coordinates();
    temporary.setAttrs({
      x: Math.min(start.x, p.x),
      y: Math.min(start.y, p.y),
      width: Math.abs(p.x - start.x),
      height: Math.abs(p.y - start.y),
    });
  });
  stage.on("mouseup touchend", () => {
    if (!start || !temporary || !drawingContext) return;
    if (!validContext(drawingContext.generation, drawingContext.annotation)) {
      cancelDrawing();
      return;
    }
    const { annotation: a, tool } = drawingContext,
      x = Math.max(0, temporary.x()),
      y = Math.max(0, temporary.y()),
      x2 = Math.min(a.width, temporary.x() + temporary.width()),
      y2 = Math.min(a.height, temporary.y() + temporary.height());
    cancelDrawing();
    if (x2 - x < 2 || y2 - y < 2) return;
    store.checkpoint();
    const obj = instance(
      store.defaultClass,
      tool === "box" ? [x, y, x2, y2] : null,
    );
    if (tool === "promptbox") obj.prompt_box = [x, y, x2, y2];
    a.instances.push(obj);
    store.selected = obj.id;
    store.changed(tool === "box" ? "detection" : "segmentation");
    if (tool === "promptbox") store.promptsChanged();
  });
  window.addEventListener("keydown", key);
  window.addEventListener("keyup", release);
  if (store.current) void loadImage();
});
async function loadImage() {
  const generation = ++imageGeneration;
  background = null;
  maskCache.clear();
  maskHitCache.clear();
  outlineCache = null;
  loadingMasks.clear();
  const id = store.current?.id;
  if (!id) return;
  const im = new Image();
  im.src = projectResource(`/images/${id}/file`);
  try {
    await im.decode();
    if (generation !== imageGeneration || id !== store.current?.id) return;
    background = im;
    fit();
  } catch {
    if (generation === imageGeneration) store.error = "Could not load image";
  }
}
// Invalidate synchronously, including A→B→A or tool changes within one Vue tick.
watch(
  [
    () => store.meta?.id,
    () => store.meta?.session,
    () => store.meta?.root,
    () => store.current?.id,
    () => store.tool,
    () => store.selectionTarget,
    () => store.navigating,
    () => store.annotation,
  ],
  invalidateGestures,
  { flush: "sync" },
);
watch(
  () => store.candidate?.overlay,
  async (source) => {
    candidateImage = null;
    candidateImageKey = source || "";
    draw();
    if (!source) return;
    const image = new Image();
    image.src = source;
    try {
      await image.decode();
      if (candidateImageKey !== source) return;
      candidateImage = image;
      draw();
    } catch {
      if (candidateImageKey === source) {
        store.cancelCandidates();
        store.error = "Could not load candidate preview";
      }
    }
  },
);
watch(
  [() => store.meta?.id, () => store.meta?.session, () => store.current?.id],
  loadImage,
);
watch(
  () => [
    store.annotation,
    store.selected,
    store.selectedPrompt,
    store.selectedGeometry,
    store.selectionTarget,
    store.dirty,
    store.meta,
  ],
  draw,
  {
    deep: true,
  },
);
watch(
  () => store.tool,
  () => {
    panning.value = false;
    stage?.draggable(space || store.tool === "pan");
    draw();
  },
);
onBeforeUnmount(() => {
  invalidateGestures();
  imageGeneration++;
  maskCache.clear();
  maskHitCache.clear();
  outlineCache = null;
  loadingMasks.clear();
  background = null;
  candidateImageKey = "";
  candidateImage = null;
  observer?.disconnect();
  stage?.destroy();
  window.removeEventListener("blur", blur);
  window.removeEventListener("keydown", key);
  window.removeEventListener("keyup", release);
});
defineExpose({ fit, zoom, ratio });
</script>
<template>
  <div
    ref="host"
    class="canvas-host"
    :style="{ '--tool-cursor': cursor }"
  ></div>
</template>
