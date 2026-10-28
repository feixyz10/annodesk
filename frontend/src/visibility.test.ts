import { afterEach, expect, it, vi } from "vitest";
import { effectScope, reactive } from "vue";
import { createVisibility } from "./visibility";
import { instance } from "./api";
const cleanup: (() => void)[] = [];
afterEach(() => {
  cleanup.splice(0).forEach((fn) => fn());
  vi.unstubAllGlobals();
});
function setup() {
  const obj = instance(null, [1, 1, 8, 8]);
  obj.id = "a";
  obj.mask = {};
  const context = reactive({ project: "p", image: "one", instances: [obj] });
  const scope = effectScope();
  cleanup.push(() => scope.stop());
  const view = scope.run(() => createVisibility(() => context))!;
  return { context, obj: context.instances[0], view };
}
it("combines project display with local choices, restores images and never mutates geometry", () => {
  const { context, obj, view } = setup();
  const before = JSON.stringify(obj);
  view.setLayer(obj.id, "mask", false);
  expect(view.layerVisible(obj, "box")).toBe(true);
  expect(view.layerVisible(obj, "mask")).toBe(false);
  view.applyView("segmentation");
  expect(view.layerVisible(obj, "box")).toBe(false);
  expect(view.layerVisible(obj, "mask")).toBe(false);
  view.resetImageLayers();
  expect(view.layerVisible(obj, "mask")).toBe(true);
  expect(view.layerVisible(obj, "box")).toBe(false);
  view.setLayer("image", "mask", false);
  context.image = "two";
  expect(view.layerVisible(obj, "mask")).toBe(true);
  context.image = "one";
  expect(view.layerVisible(obj, "mask")).toBe(false);
  context.project = "q";
  expect(view.globalLayers.value.box).toBe(true);
  context.project = "p";
  expect(view.globalLayers.value.box).toBe(false);
  expect(view.layerVisible(obj, "mask")).toBe(false);
  expect(JSON.stringify(obj)).toBe(before);
});
it("recovers from blocked/malformed storage and respects legacy hidden objects until explicitly shown", () => {
  vi.stubGlobal("localStorage", {
    getItem: () => "{broken",
    setItem: () => {
      throw new Error("blocked");
    },
  });
  const { context, obj, view } = setup();
  obj.hidden = true;
  obj.locked = true;
  expect(view.layerVisible(obj, "mask")).toBe(false);
  view.setLayer(obj.id, "box", false);
  view.setLayer(obj.id, "mask", true);
  expect(view.layerVisible(obj, "mask")).toBe(true);
  expect(view.layerVisible(obj, "box")).toBe(false);
  context.image = "two";
  context.image = "one";
  expect(view.layerVisible(obj, "mask")).toBe(true);
  expect(obj.hidden).toBe(true);
  expect(obj.locked).toBe(true);
});
it("restores preferences after reopening and isolates copied project roots", () => {
  const data = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (key: string) => data.get(key) ?? null,
    setItem: (key: string, value: string) => data.set(key, value),
  });
  const first = setup();
  first.view.applyView("detection");
  first.view.setLayer("a", "box", false);
  const second = setup();
  expect(second.view.globalLayers.value).toEqual({
    box: true,
    mask: false,
    prompts: false,
  });
  expect(second.view.layerVisible(second.obj, "box")).toBe(false);
  second.context.project = "copy-of-p";
  expect(second.view.layerVisible(second.obj, "box")).toBe(true);
});
it("restores a whole image layer from mixed visibility without changing other layers or global gates", () => {
  const { context, obj, view } = setup();
  const second = instance(null, [2, 2, 6, 6]);
  second.id = "b";
  context.instances.push(second, instance(null));
  const before = JSON.stringify(context.instances);
  view.setLayer(obj.id, "box", false);
  view.setLayer(obj.id, "mask", false);
  expect(view.imageLayerState("box")).toBe("mixed");
  view.toggleImageLayer("box");
  expect(view.imageLayerState("box")).toBe("all");
  expect(view.layerVisible(obj, "mask")).toBe(false);
  view.toggleImageLayer("box");
  expect(view.imageLayerState("box")).toBe("none");
  view.toggleImageLayer("box");
  expect(view.imageLayerState("box")).toBe("all");
  view.setLayer("global", "box", false);
  view.toggleImageLayer("box");
  expect(view.globalLayers.value.box).toBe(false);
  context.image = "two";
  context.image = "one";
  view.setLayer("global", "box", true);
  expect(view.imageLayerState("box")).toBe("all");
  expect(JSON.stringify(context.instances)).toBe(before);
});

it("bulk hiding allows one geometry or object to be shown and aggregates eyes across the full image", () => {
  const { context, obj, view } = setup();
  obj.points = [{ x: 2, y: 2, positive: true }];
  const second = instance(null, [2, 2, 6, 6]);
  second.id = "b";
  context.instances.push(second);
  const before = JSON.stringify(context.instances);
  view.setImageHidden(true);
  expect(view.imageHasVisibleGeometry.value).toBe(false);
  expect(view.objectHidden(obj)).toBe(true);
  expect(view.objectHidden(second)).toBe(true);
  view.setLayer(obj.id, "mask", true);
  expect(view.objectHidden(obj)).toBe(false);
  expect(view.imageHasVisibleGeometry.value).toBe(true);
  expect(view.layerVisible(obj, "box")).toBe(false);
  expect(view.layerVisible(obj, "prompts")).toBe(false);
  expect(view.objectHidden(second)).toBe(true);
  view.setLayer(obj.id, "mask", false);
  expect(view.imageHasVisibleGeometry.value).toBe(false);
  view.setObjectHidden(second.id, false);
  expect(view.layerVisible(second, "box")).toBe(true);
  expect(view.objectHidden(obj)).toBe(true);
  view.setImageHidden(true);
  view.toggleImageLayer("box");
  expect(view.imageLayerState("box")).toBe("all");
  expect(view.objectHidden(obj)).toBe(false);
  expect(view.layerVisible(obj, "mask")).toBe(false);
  context.image = "two";
  expect(view.layerVisible(obj, "mask")).toBe(true);
  context.image = "one";
  expect(view.layerVisible(obj, "mask")).toBe(false);
  expect(view.layerVisible(obj, "box")).toBe(true);
  expect(JSON.stringify(context.instances)).toBe(before);
});
it("eye summaries respect project-wide visibility and absent geometry", () => {
  const { obj, context, view } = setup();
  view.setImageHidden(false);
  view.setLayer("global", "box", false);
  view.setLayer("global", "mask", false);
  expect(view.imageHasVisibleGeometry.value).toBe(false);
  expect(view.objectHidden(obj)).toBe(true);
  view.setLayer("global", "mask", true);
  expect(view.objectHidden(obj)).toBe(false);
  context.instances = [];
  expect(view.imageHasVisibleGeometry.value).toBe(false);
});
it("flattens saved master gates on a child edit without revealing other objects", () => {
  vi.stubGlobal("localStorage", {
    getItem: (key: string) =>
      key.endsWith(":one")
        ? JSON.stringify({
            imageHidden: true,
            layers: { box: true, mask: true, prompts: true },
          })
        : null,
    setItem: vi.fn(),
  });
  const { obj, context, view } = setup();
  const second = instance(null, [2, 2, 6, 6]);
  second.id = "b";
  context.instances.push(second);
  expect(view.imageHasVisibleGeometry.value).toBe(false);
  view.setLayer(obj.id, "mask", true);
  expect(view.layerVisible(obj, "mask")).toBe(true);
  expect(view.layerVisible(obj, "box")).toBe(false);
  expect(view.objectHidden(second)).toBe(true);
});
