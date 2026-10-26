import { afterEach, expect, it } from "vitest";
import { createRenderer, h, nextTick, ssrContextKey } from "vue";
import { createPinia, setActivePinia } from "pinia";
import { instance } from "../api";
import { useProject } from "../stores/project";
import ClearImageAnnotations from "./ClearImageAnnotations.vue";
let dispose: () => void;
afterEach(() => dispose?.());
async function setup() {
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
  b.locked = true;
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
  const component = { ...ClearImageAnnotations, render: () => h("div") };
  const app = renderer.createApp({
    render: () =>
      h(component as any, {
        show: true,
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
it("defaults to preserving locked instances and confirms in one undo step", async () => {
  const { store, state } = await setup();
  expect(state.includeLocked).toBe(false);
  expect(state.targets).toHaveLength(1);
  state.confirm();
  expect(store.annotation!.instances).toHaveLength(1);
  expect(store.annotation!.instances[0].locked).toBe(true);
  expect(store.history).toHaveLength(1);
});
it("refuses a confirmation after the active image changes", async () => {
  const { store, state } = await setup();
  store.current = { id: "b", path: "b.jpg" };
  state.confirm();
  expect(store.annotation!.instances).toHaveLength(2);
  expect(store.history).toHaveLength(0);
});
it("includes locked instances only when explicitly enabled", async () => {
  const { store, state } = await setup();
  state.includeLocked = true;
  expect(state.targets).toHaveLength(2);
  state.confirm();
  expect(store.annotation!.instances).toHaveLength(0);
  store.undo();
  expect(store.annotation!.instances).toHaveLength(2);
});
