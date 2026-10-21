<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref, watch } from "vue";
import Konva from "konva";
import { useProject } from "../stores/project";
import { apiBase, instance } from "../api";
const store = useProject(),
  host = ref<HTMLDivElement>(),
  ratio = ref(1);
let stage: Konva.Stage,
  layer: Konva.Layer,
  background: HTMLImageElement | null = null,
  observer: ResizeObserver,
  temporary: Konva.Rect | null = null,
  start: { x: number; y: number } | null = null,
  space = false,
  transformer: Konva.Transformer;
function fit() {
  if (!stage || !store.annotation) return;
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
  if (!store.annotation) return;
  const a = store.annotation;
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
    for (const points of object.polygons) {
      const shape = new Konva.Line({
        points: points.flat(),
        closed: true,
        fill: color + "55",
        stroke: color,
        strokeWidth: 1.5,
        strokeScaleEnabled: false,
      });
      shape.on("click tap", () => {
        store.selected = object.id;
      });
      layer.add(shape);
    }
    const box = object.box ?? object.prompt_box;
    if (box) {
      const shape = new Konva.Rect({
        x: box[0],
        y: box[1],
        width: box[2] - box[0],
        height: box[3] - box[1],
        stroke: color,
        strokeWidth: store.selected === object.id ? 2.5 : 1.5,
        strokeScaleEnabled: false,
        dash: object.box ? [] : [5, 3],
        draggable: store.tool === "select" && !object.locked,
      });
      shape.on("mousedown touchstart", (e) => {
        if (store.tool === "select") {
          e.cancelBubble = true;
          store.selected = object.id;
        }
      });
      shape.on("dragstart", () => store.checkpoint());
      shape.on("dragend", () => {
        const w = shape.width(),
          h = shape.height(),
          x = Math.max(0, Math.min(a.width - w, shape.x())),
          y = Math.max(0, Math.min(a.height - h, shape.y()));
        if (object.box) object.box = [x, y, x + w, y + h];
        else object.prompt_box = [x, y, x + w, y + h];
        store.changed(true);
      });
      shape.on("transformstart", () => store.checkpoint());
      shape.on("transformend", () => {
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
        if (object.box) object.box = [x, y, x + w, y + h];
        else object.prompt_box = [x, y, x + w, y + h];
        store.changed(true);
      });
      layer.add(shape);
      if (
        store.selected === object.id &&
        !object.locked &&
        store.tool === "select"
      ) {
        transformer = new Konva.Transformer({
          nodes: [shape],
          rotateEnabled: false,
          flipEnabled: false,
          ignoreStroke: true,
          anchorSize: 7,
          borderEnabled: false,
        });
        layer.add(transformer);
      }
    }
    for (const p of object.points)
      layer.add(
        new Konva.Circle({
          x: p.x,
          y: p.y,
          radius: 4 / stage.scaleX(),
          fill: p.positive ? "#24835d" : "#c14d5c",
          stroke: "white",
          strokeWidth: 1.5 / stage.scaleX(),
          listening: false,
        }),
      );
  }
  layer.batchDraw();
}
function key(e: KeyboardEvent) {
  if ((e.target as HTMLElement).closest("input,textarea,select,button")) return;
  if (e.code === "Space") {
    e.preventDefault();
    space = true;
    stage?.draggable(true);
  }
}
function release(e: KeyboardEvent) {
  if (e.code === "Space") {
    space = false;
    stage?.draggable(store.tool === "pan");
  }
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
    stage.size({
      width: host.value!.clientWidth,
      height: host.value!.clientHeight,
    });
    draw();
  });
  observer.observe(host.value!);
  stage.on("wheel", (e) => {
    e.evt.preventDefault();
    zoom(Math.exp(-e.evt.deltaY * 0.002), stage.getPointerPosition()!);
  });
  stage.on("mousedown touchstart", (e) => {
    if (!store.annotation || store.navigating || space || store.tool === "pan")
      return;
    const p = coordinates(),
      a = store.annotation;
    if (p.x < 0 || p.y < 0 || p.x > a.width || p.y > a.height) return;
    if (["box", "promptbox"].includes(store.tool)) {
      start = p;
      temporary = new Konva.Rect({
        x: p.x,
        y: p.y,
        width: 1,
        height: 1,
        stroke: "#315fe9",
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
      store.changed(true);
    } else if (e.target === stage || e.target instanceof Konva.Image)
      store.selected = null;
  });
  stage.on("mousemove touchmove", () => {
    if (!start || !temporary) return;
    const p = coordinates();
    temporary.setAttrs({
      x: Math.min(start.x, p.x),
      y: Math.min(start.y, p.y),
      width: Math.abs(p.x - start.x),
      height: Math.abs(p.y - start.y),
    });
  });
  stage.on("mouseup touchend", () => {
    if (!start || !temporary || !store.annotation) return;
    const a = store.annotation,
      x = Math.max(0, temporary.x()),
      y = Math.max(0, temporary.y()),
      x2 = Math.min(a.width, temporary.x() + temporary.width()),
      y2 = Math.min(a.height, temporary.y() + temporary.height());
    temporary.destroy();
    temporary = null;
    start = null;
    if (x2 - x < 2 || y2 - y < 2) return;
    store.checkpoint();
    const obj = instance(
      store.defaultClass,
      store.tool === "box" ? [x, y, x2, y2] : null,
    );
    if (store.tool === "promptbox") obj.prompt_box = [x, y, x2, y2];
    a.instances.push(obj);
    store.selected = obj.id;
    store.changed(true);
  });
  window.addEventListener("keydown", key);
  window.addEventListener("keyup", release);
  if (store.current) void loadImage();
});
async function loadImage() {
  background = null;
  const id = store.current?.id;
  if (!id) return;
  const im = new Image();
  im.src = apiBase + `/images/${id}/file`;
  try {
    await im.decode();
    if (id !== store.current?.id) return;
    background = im;
    fit();
  } catch {
    store.error = "Could not load image";
  }
}
watch(() => store.current?.id, loadImage);
watch(() => [store.annotation, store.selected, store.meta], draw, {
  deep: true,
});
watch(
  () => store.tool,
  () => {
    stage?.draggable(store.tool === "pan");
    draw();
  },
);
onBeforeUnmount(() => {
  observer?.disconnect();
  stage?.destroy();
  window.removeEventListener("keydown", key);
  window.removeEventListener("keyup", release);
});
defineExpose({ fit, zoom, ratio });
</script>
<template><div ref="host" class="canvas-host"></div></template>
