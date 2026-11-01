/** Transient mask gestures. Only completed edits are handed to the project store. */
import Konva from "konva";
import type { useProject } from "./stores/project";
import {
  instancePixels,
  maskCanvas,
  paintSegment,
  fillPolygon,
  type PixelPoint,
} from "./manualMasks";
type Store = ReturnType<typeof useProject>;
export function createManualCanvas(
  store: Store,
  stage: Konva.Stage,
  host: HTMLElement,
  redraw: () => void,
) {
  const layer = new Konva.Layer({ listening: false });
  stage.add(layer);
  let context: ReturnType<Store["beginManualEdit"]> = null;
  let pixels: Uint8Array | null = null,
    image: HTMLCanvasElement | null = null;
  let points: number[][] = [],
    last: PixelPoint | null = null,
    cursor: PixelPoint | null = null;
  let pointer: number | null = null,
    frame = 0;
  let width = 0,
    height = 0,
    diameter = 24,
    add = true,
    color = "#657286";
  const position = (e: PointerEvent) => {
    const rect = host.getBoundingClientRect(),
      scale = stage.scaleX();
    return {
      x: (e.clientX - rect.left - stage.x()) / scale,
      y: (e.clientY - rect.top - stage.y()) / scale,
    };
  };
  function releasePointer() {
    const id = pointer;
    pointer = null;
    if (id !== null && host.hasPointerCapture?.(id))
      host.releasePointerCapture(id);
  }
  function cancel() {
    context = null;
    pixels = null;
    image = null;
    points = [];
    last = null;
    store.manualBusy = false;
    store.polygonVertices = 0;
    releasePointer();
    render();
    redraw();
  }
  function valid() {
    return !!context && store.validManualEdit(context);
  }
  function begin() {
    context = store.beginManualEdit();
    if (!context || !store.annotation) return false;
    width = store.annotation.width;
    height = store.annotation.height;
    try {
      pixels = instancePixels(store.object ?? null, width, height);
    } catch (e) {
      store.error = String(e);
      cancel();
      return false;
    }
    color =
      store.meta?.classes.find(
        (c) => c.id === (store.object?.class_id ?? store.defaultClass),
      )?.color ?? "#657286";
    diameter = store.tool === "eraser" ? store.eraserSize : store.brushSize;
    add = store.tool !== "eraser" && store.polygonMode !== "subtract";
    if (store.tool === "brush") add = true;
    image = maskCanvas(pixels, width, height, color);
    store.manualBusy = true;
    redraw();
    return true;
  }
  function paint(a: PixelPoint, b: PixelPoint) {
    if (!pixels || !image) return;
    if (!paintSegment(pixels, width, height, a, b, diameter, add)) return;
    // Update only the swept region, not a full RGBA image on every pointer event.
    const r = diameter / 2;
    const x = Math.max(0, Math.floor(Math.min(a.x, b.x) - r)),
      y = Math.max(0, Math.floor(Math.min(a.y, b.y) - r));
    const w = Math.min(width, Math.ceil(Math.max(a.x, b.x) + r)) - x;
    const h = Math.min(height, Math.ceil(Math.max(a.y, b.y) + r)) - y;
    if (w <= 0 || h <= 0) return;
    const ctx = image.getContext("2d")!,
      data = ctx.createImageData(w, h);
    const rgb = [1, 3, 5].map((i) => parseInt(color.slice(i, i + 2), 16));
    for (let row = 0; row < h; row++)
      for (let col = 0; col < w; col++) {
        const i = (row * w + col) * 4;
        data.data[i] = rgb[0];
        data.data[i + 1] = rgb[1];
        data.data[i + 2] = rgb[2];
        data.data[i + 3] = pixels[(row + y) * width + col + x] ? 90 : 0;
      }
    ctx.putImageData(data, x, y);
  }
  function render() {
    layer.destroyChildren();
    if (!store.manualTool) {
      layer.batchDraw();
      return;
    }
    const scale = stage.scaleX();
    if (context && image)
      layer.add(new Konva.Image({ image, width, height, listening: false }));
    if (points.length) {
      const path = cursor ? [...points, [cursor.x, cursor.y]] : points;
      layer.add(
        new Konva.Line({
          points: path.flat(),
          stroke: add ? "#315fe9" : "#b34445",
          strokeWidth: 2,
          strokeScaleEnabled: false,
          closed: path.length > 2,
          fill: add ? "rgba(49,95,233,0.14)" : "rgba(179,68,69,0.14)",
          fillRule: "evenodd",
          dash: [5, 3],
          listening: false,
        }),
      );
      for (const p of points)
        layer.add(
          new Konva.Circle({
            x: p[0],
            y: p[1],
            radius: 3 / scale,
            fill: "white",
            stroke: "#315fe9",
            strokeWidth: 1 / scale,
            listening: false,
          }),
        );
    }
    if (
      cursor &&
      !stage.draggable() &&
      !store.manualBlocked &&
      store.tool !== "polygon"
    ) {
      const radius =
        (store.tool === "eraser" ? store.eraserSize : store.brushSize) / 2;
      for (const [stroke, strokeWidth] of [
        ["white", 3],
        ["#25344a", 1],
      ] as const)
        layer.add(
          new Konva.Circle({
            ...cursor,
            radius,
            stroke,
            strokeWidth,
            strokeScaleEnabled: false,
            listening: false,
          }),
        );
      const d = 3 / scale;
      for (const coords of [
        [cursor.x - d, cursor.y, cursor.x + d, cursor.y],
        [cursor.x, cursor.y - d, cursor.x, cursor.y + d],
      ])
        layer.add(
          new Konva.Line({
            points: coords,
            stroke: "#25344a",
            strokeWidth: 1,
            strokeScaleEnabled: false,
            listening: false,
          }),
        );
      const x = cursor.x + radius + 7 / scale,
        y = cursor.y - radius;
      layer.add(
        new Konva.Line({
          points: [x - d, y, x + d, y],
          stroke: "#25344a",
          strokeWidth: 2,
          strokeScaleEnabled: false,
          listening: false,
        }),
      );
      if (store.tool === "brush")
        layer.add(
          new Konva.Line({
            points: [x, y - d, x, y + d],
            stroke: "#25344a",
            strokeWidth: 2,
            strokeScaleEnabled: false,
            listening: false,
          }),
        );
    }
    layer.batchDraw();
  }
  function schedule() {
    if (!frame)
      frame = requestAnimationFrame(() => {
        frame = 0;
        render();
      });
  }
  function commit() {
    if (!context || !pixels) return;
    const captured = context,
      result = pixels;
    context = null;
    pixels = null;
    image = null;
    points = [];
    last = null;
    store.manualBusy = false;
    store.polygonVertices = 0;
    releasePointer();
    store.commitManualMask(captured, result);
    render();
    redraw();
  }
  function finish() {
    if (!valid() || !pixels || points.length < 3) return;
    fillPolygon(pixels, width, height, points, add);
    commit();
  }
  function down(e: PointerEvent) {
    if (
      !store.manualTool ||
      e.button !== 0 ||
      stage.draggable() ||
      store.manualBlocked ||
      document.querySelector(".n-modal")
    )
      return;
    const p = position(e),
      ann = store.annotation;
    if (!ann || p.x < 0 || p.y < 0 || p.x >= ann.width || p.y >= ann.height)
      return;
    // Pointer work belongs to the canvas, not the toolbar button last clicked.
    host.focus({ preventScroll: true });
    e.preventDefault();
    if (context && !valid()) cancel();
    if (store.tool === "polygon") {
      if (!context && !begin()) return;
      if (
        points.length >= 3 &&
        Math.hypot(p.x - points[0][0], p.y - points[0][1]) * stage.scaleX() < 8
      ) {
        finish();
        return;
      }
      points.push([p.x, p.y]);
      store.polygonVertices = points.length;
      cursor = p;
      render();
      return;
    }
    if (!begin()) return;
    pointer = e.pointerId;
    host.setPointerCapture?.(pointer);
    last = p;
    cursor = p;
    paint(p, p);
    render();
  }
  function move(e: PointerEvent) {
    if (!store.manualTool) return;
    cursor = position(e);
    if (context && !valid()) {
      cancel();
      return;
    }
    if (pointer === e.pointerId && last) {
      paint(last, cursor);
      last = cursor;
    }
    schedule();
  }
  function up(e: PointerEvent) {
    if (pointer !== e.pointerId) return;
    if (!valid()) {
      cancel();
      return;
    }
    if (last) paint(last, position(e));
    commit();
  }
  function leave() {
    if (pointer === null) {
      cursor = null;
      render();
    }
  }
  function lost() {
    if (pointer !== null) cancel();
  }
  function key(e: KeyboardEvent): boolean {
    if (!store.manualTool || store.candidates) return false;
    const k = e.key.toLowerCase();
    if (
      context &&
      (k === "escape" || ((e.ctrlKey || e.metaKey) && k === "z"))
    ) {
      if (k !== "escape" && points.length) {
        points.pop();
        store.polygonVertices = points.length;
        if (!points.length) cancel();
        else render();
      } else cancel();
      e.preventDefault();
      return true;
    }
    if (
      context &&
      (["x", "delete", "1", "2", "3"].includes(k) ||
        (k === "backspace" && store.tool !== "polygon"))
    ) {
      e.preventDefault();
      return true;
    }
    if (store.tool === "polygon" && k === "backspace" && points.length) {
      points.pop();
      store.polygonVertices = points.length;
      if (!points.length) cancel();
      else render();
      e.preventDefault();
      return true;
    }
    if (k === "enter") {
      if (store.tool === "polygon") finish();
      e.preventDefault();
      return true;
    }
    if (["[", "]"].includes(k) && store.tool !== "polygon") {
      const field = store.tool === "eraser" ? "eraserSize" : "brushSize";
      const size = store[field];
      store[field] = Math.max(
        1,
        Math.min(
          512,
          size + (k === "[" ? -1 : 1) * Math.max(1, Math.round(size * 0.1)),
        ),
      );
      e.preventDefault();
      render();
      return true;
    }
    return false;
  }
  host.addEventListener("pointerdown", down);
  host.addEventListener("pointermove", move);
  host.addEventListener("pointerup", up);
  host.addEventListener("pointercancel", cancel);
  host.addEventListener("lostpointercapture", lost);
  host.addEventListener("pointerleave", leave);
  return {
    cancel,
    finish,
    key,
    render,
    isPainting: () => pointer !== null,
    hides: (id: string) => !!context && store.selected === id,
    validate: () => {
      if (context && !valid()) cancel();
    },
    destroy: () => {
      if (frame) cancelAnimationFrame(frame);
      cancel();
      layer.destroy();
      host.removeEventListener("pointerdown", down);
      host.removeEventListener("pointermove", move);
      host.removeEventListener("pointerup", up);
      host.removeEventListener("pointercancel", cancel);
      host.removeEventListener("lostpointercapture", lost);
      host.removeEventListener("pointerleave", leave);
    },
  };
}
