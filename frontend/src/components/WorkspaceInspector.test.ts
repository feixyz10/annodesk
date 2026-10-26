import { afterEach, expect, it, vi } from "vitest";
import { createSSRApp, createRenderer, h, nextTick, ssrContextKey } from "vue";
import { createPinia, setActivePinia } from "pinia";
import { renderToString } from "@vue/server-renderer";
import { instance } from "../api";
import { setLocale } from "../i18n";
import { useProject } from "../stores/project";
import WorkspaceInspector from "./WorkspaceInspector.vue";
vi.mock("naive-ui", () => ({ NDropdown: { ssrRender() {} } }));
vi.mock("./SelectedObjectActions.vue", () => ({
  default: {
    ssrRender(_: unknown, push: (s: string) => void) {
      push("<div>Selected object properties</div>");
    },
  },
}));
afterEach(() => {
  setLocale("en");
  vi.unstubAllGlobals();
});
it.each(["en", "zh-CN"])(
  "keeps fixed geometry slots and permanent image properties available (%s)",
  async (language) => {
    setLocale(language);
    const pinia = createPinia();
    setActivePinia(pinia);
    const store = useProject();
    const obj = instance(null, [0, 0, 8, 8]);
    obj.mask = { counts: "test" };
    obj.prompt_box = [1, 1, 7, 7];
    store.annotation = {
      revision: 0,
      instances: [obj],
      detection_review: "pending",
      segmentation_review: "pending",
      excluded: false,
      tags: [],
      notes: "",
      explicit_empty: {},
      width: 10,
      height: 10,
    };
    const app = createSSRApp(WorkspaceInspector);
    app.use(pinia);
    const html = await renderToString(app);
    for (const label of language === "en"
      ? [
          "Search objects",
          "Detection box",
          "Mask",
          "SAM prompts",
          "Hide object",
          "Lock object",
          "New object",
        ]
      : [
          "搜索实例",
          "检测框",
          "掩膜",
          "SAM提示",
          "隐藏实例",
          "锁定实例",
          "新物体",
        ])
      expect(html).toContain(label);
    expect(html).not.toContain('role="tablist"');
    expect(html).toContain(language === "en" ? "Image properties" : "图片属性");
    for (const column of [
      "box",
      "mask",
      "prompts",
      "visibility",
      "lock",
      "more",
    ])
      expect(html).toContain(`data-column="${column}"`);
    expect(html).toContain('role="separator"');
    expect(html).toContain('aria-valuenow="55"');
    expect(html).not.toContain('id="object-properties"');
    expect(html).toContain('id="image-properties"');
  },
);
it.each(["bogus", "99", "-1"])(
  "uses a safe list height for invalid saved proportions (%s)",
  async (value) => {
    vi.stubGlobal("localStorage", { getItem: () => value });
    const app = createSSRApp(WorkspaceInspector);
    app.use(createPinia());
    expect(await renderToString(app)).toContain('aria-valuenow="55"');
  },
);

let unmount: (() => void) | undefined;
afterEach(() => unmount?.());
async function mountedInspector(initialSelected: string | null = null) {
  const renderer = createRenderer<any, any>({
    createElement: () => ({
      scrollTop: 100,
      querySelectorAll: () => [],
      getBoundingClientRect: () => ({ top: 0, height: 600 }),
    }),
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
  const pinia = createPinia();
  setActivePinia(pinia);
  const store = useProject();
  store.meta = {
    id: "project",
    session: "session",
    root: "/tmp/project",
    classes: [],
    tags: [],
    image_count: 2,
  };
  store.current = { id: "a", path: "a.jpg" };
  const a = instance(null, [1, 1, 8, 8]),
    b = instance(null);
  a.id = "a-object";
  b.id = "b-object";
  a.prompt_box = [1, 1, 8, 8];
  b.mask = { size: [10, 10], counts: "test" };
  store.annotation = {
    revision: 0,
    instances: [a, b],
    detection_review: "pending",
    segmentation_review: "pending",
    excluded: false,
    tags: [],
    notes: "",
    explicit_empty: {},
    width: 10,
    height: 10,
  };
  store.selected = initialSelected;
  let vm: any;
  const component = {
    ...WorkspaceInspector,
    render: () => h("div", { ref: "container" }, [h("div", { ref: "list" })]),
  };
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
  unmount = () => app.unmount();
  await nextTick();
  return { store, state: vm.$.setupState };
}
it("expands only the selected row, preserves selection on collapse and keeps toggles independent", async () => {
  const { store, state } = await mountedInspector();
  state.select("a-object");
  await nextTick();
  expect(state.expanded).toBe("a-object");
  state.disclosure("a-object");
  expect(state.expanded).toBeNull();
  expect(store.selected).toBe("a-object");
  state.geometry("b-object", "mask");
  await nextTick();
  expect(state.expanded).toBe("b-object");
  expect(store.selectedGeometry).toBe("mask");
  state.toggle("a-object", "hidden");
  state.toggle("a-object", "locked");
  expect(store.selected).toBe("b-object");
  expect(store.selectedGeometry).toBe("mask");
  expect(store.annotation!.instances[0]).toMatchObject({
    hidden: true,
    locked: true,
  });
});
it("preserves object search and expanded properties on metadata refresh", async () => {
  const { store, state } = await mountedInspector();
  state.select("a-object");
  state.query = "a";
  await nextTick();
  store.meta = { ...store.meta!, image_count: 3 };
  await nextTick();
  expect(state.query).toBe("a");
  expect(state.expanded).toBe("a-object");
  store.meta = { ...store.meta!, session: "new-session" };
  await nextTick();
  expect(state.query).toBe("");
  expect(state.expanded).toBeNull();
});
it("rejects an opening menu after navigation and rejects destructive actions on locked objects", async () => {
  const { store, state } = await mountedInspector();
  const event = { clientX: 10, clientY: 20, currentTarget: null };
  const opening = state.openMenu(event, "a-object");
  store.current = { id: "b", path: "b.jpg" };
  await opening;
  expect(state.menu).toBeNull();
  await state.openMenu(event, "a-object");
  expect(state.menu?.id).toBe("a-object");
  store.annotation!.instances[0].locked = true;
  state.menuAction("delete-object");
  expect(store.annotation!.instances).toHaveLength(2);
  store.current = { id: "a", path: "a.jpg" };
  state.menuAction("delete-object");
  expect(store.annotation!.instances).toHaveLength(2);
});
it("retains all geometry slots even for a prompt-only object", async () => {
  const pinia = createPinia();
  setActivePinia(pinia);
  const store = useProject();
  const obj = instance(null);
  obj.points = [{ x: 1, y: 1, positive: true }];
  store.annotation = {
    revision: 0,
    instances: [obj],
    detection_review: "pending",
    segmentation_review: "pending",
    excluded: false,
    tags: [],
    notes: "",
    explicit_empty: {},
    width: 10,
    height: 10,
  };
  const app = createSSRApp(WorkspaceInspector);
  app.use(pinia);
  const html = await renderToString(app);
  expect(html).toContain('aria-label="No detection box"');
  expect(html).toContain('aria-label="No mask"');
  expect(html.match(/data-column=/g)).toHaveLength(6);
});

it("toggles an already-selected row without losing its selected geometry", async () => {
  const { store, state } = await mountedInspector();
  state.geometry("b-object", "mask");
  await nextTick();
  state.select("b-object");
  await nextTick();
  expect(state.expanded).toBeNull();
  expect(store.selected).toBe("b-object");
  expect(store.selectedGeometry).toBe("mask");
  state.select("b-object");
  await nextTick();
  expect(state.expanded).toBe("b-object");
  state.geometry("a-object", "box");
  await nextTick();
  expect(state.expanded).toBe("a-object");
});

it("starts object details collapsed even when an object is already selected", async () => {
  const { store, state } = await mountedInspector("a-object");
  expect(state.objects).toHaveLength(2);
  expect(state.expanded).toBeNull();
  expect(store.selected).toBe("a-object");
  state.select("a-object");
  await nextTick();
  expect(state.expanded).toBe("a-object");
  state.select("a-object");
  await nextTick();
  expect(state.expanded).toBeNull();
  expect(store.history).toHaveLength(0);
});
