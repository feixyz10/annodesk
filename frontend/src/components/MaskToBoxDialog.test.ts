import { afterEach, expect, it, vi } from "vitest";
import { createRenderer, h, nextTick, ssrContextKey } from "vue";
import { createPinia, setActivePinia } from "pinia";
import { instance } from "../api";
import { useProject } from "../stores/project";
import MaskToBoxDialog from "./MaskToBoxDialog.vue";
let dispose: () => void;
afterEach(() => dispose?.());
async function setup(mode: "image" | "selected" = "image") {
  const pinia = createPinia();
  setActivePinia(pinia);
  const store = useProject();
  store.meta = {
    id: "p",
    session: "s",
    root: "/tmp/p",
    classes: [],
    tags: [],
    image_count: 1,
  };
  store.current = { id: "a", path: "a.jpg" };
  const a = instance(null, [1, 1, 3, 3]),
    b = instance(null, [4, 4, 8, 8]);
  a.polygons = [
    [
      [1, 1],
      [3, 1],
      [3, 3],
    ],
  ];
  b.polygons = [
    [
      [4, 4],
      [8, 4],
      [8, 8],
    ],
  ];
  b.box = null;
  store.selected = a.id;
  store.boxConversion = mode;
  store.annotation = {
    revision: 0,
    instances: [a, b],
    detection_review: "ok",
    segmentation_review: "ok",
    excluded: false,
    tags: [],
    notes: "",
    explicit_empty: {},
    width: 10,
    height: 10,
  };
  const renderer = createRenderer<any, any>({
    createElement: () => ({}),
    createText: () => ({}),
    createComment: () => ({}),
    setText() {},
    setElementText() {},
    parentNode: () => null,
    nextSibling: () => null,
    insert() {},
    remove() {},
    patchProp() {},
  });
  let vm: any;
  const component = { ...MaskToBoxDialog, render: () => h("div") };
  const app = renderer.createApp({
    render: () =>
      h(component as any, {
        ref: (v: any) => {
          vm = v;
        },
      }),
  });
  app.provide(ssrContextKey, { modules: new Set() });
  app.use(pinia);
  app.mount({});
  dispose = () => app.unmount();
  await nextTick();
  return { store, state: vm.$.setupState };
}
it.each(["image", "selected"] as const)(
  "confirms %s geometry with session padding and explicit scope",
  async (mode) => {
    const { store, state } = await setup(mode);
    const run = vi.spyOn(store, "boxesFromMasks").mockResolvedValue(undefined);
    store.boxPadding = {
      box_padding_mode: "ratio",
      box_padding_pixels: 12,
      box_padding_ratio: 0.1,
      box_padding_min: true,
    };
    expect(state.valid).toBe(true);
    state.confirm();
    expect(run).toHaveBeenCalledExactlyOnceWith(
      mode === "selected",
      mode === "selected",
    );
    expect(store.parameters("boxes_from_masks")).toMatchObject(
      store.boxPadding,
    );
    expect(store.boxConversion).toBeNull();
  },
);
it.each(["image", "session", "selection", "annotation", "navigating"])(
  "discards confirmation after %s changes",
  async (kind) => {
    const { store, state } = await setup("selected");
    const run = vi.spyOn(store, "boxesFromMasks").mockResolvedValue(undefined);
    if (kind === "image") store.current = { id: "b", path: "b.jpg" };
    if (kind === "session") store.meta!.session = "other";
    if (kind === "selection")
      store.selected = store.annotation!.instances[1].id;
    if (kind === "annotation") store.annotation = { ...store.annotation! };
    if (kind === "navigating") store.navigating = true;
    expect(store.boxConversion).toBeNull();
    state.confirm();
    expect(run).not.toHaveBeenCalled();
  },
);
it("does not run for locked targets, existing image boxes or invalid active padding", async () => {
  const { store, state } = await setup();
  const run = vi.spyOn(store, "boxesFromMasks").mockResolvedValue(undefined);
  store.annotation!.instances[1].locked = true;
  expect(state.valid).toBe(false); // The other mask already has a detection box.
  state.confirm();
  store.boxConversion = "selected";
  store.boxPadding.box_padding_pixels = -1;
  expect(state.valid).toBe(false);
  state.confirm();
  store.boxPadding.box_padding_pixels = 4;
  store.boxPadding.box_padding_ratio = Number.NaN;
  expect(state.valid).toBe(false); // Both values must satisfy the API contract.
  store.boxPadding.box_padding_min = true;
  expect(state.valid).toBe(false);
  state.confirm();
  state.close();
  expect(run).not.toHaveBeenCalled();
});
