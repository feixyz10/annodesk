import source from "./CategoryEditor.vue?raw";
import { transpile } from "typescript";
import { afterEach, expect, it, vi } from "vitest";
import * as Vue from "vue";
import { compile } from "@vue/compiler-dom";
import { compileScript, parse } from "@vue/compiler-sfc";
import { createPinia, setActivePinia } from "pinia";
import { setLocale } from "../i18n";
import { useProject } from "../stores/project";
import CategoryEditor from "./CategoryEditor.vue";

// Use the actual editor template/state and the same confirmed-update action as App.
const { descriptor } = parse(source);
const bindings = compileScript(descriptor, {
  id: "category-editor-test",
}).bindings;
const { code } = compile(descriptor.template!.content, {
  mode: "function",
  prefixIdentifiers: true,
  bindingMetadata: bindings,
});
const textModel = {
  beforeMount: (el: Node, binding: any) => {
    el.value = binding.value;
  },
  beforeUpdate: (el: Node, binding: any) => {
    el.value = binding.value;
  },
};
const render = new Function("Vue", transpile(code))({
  ...Vue,
  vModelText: textModel,
});
interface Node {
  type: string;
  children: Node[];
  parent?: Node;
  props: Record<string, any>;
  text: string;
  value?: string;
  scrollTop: number;
  clientHeight: number;
}
function node(type: string): Node {
  return {
    type,
    children: [],
    props: {},
    text: "",
    scrollTop: 0,
    clientHeight: 310,
  };
}
const renderer = Vue.createRenderer<Node, Node>({
  createElement: node,
  createText: (text) => ({ ...node("text"), text }),
  createComment: () => node("comment"),
  insert(child, parent, anchor) {
    if (child.parent)
      child.parent.children.splice(child.parent.children.indexOf(child), 1);
    const index = anchor ? parent.children.indexOf(anchor) : -1;
    parent.children.splice(
      index < 0 ? parent.children.length : index,
      0,
      child,
    );
    child.parent = parent;
  },
  remove(child) {
    child.parent?.children.splice(child.parent.children.indexOf(child), 1);
  },
  patchProp: (el, key, _previous, value) => {
    el.props[key] = value;
  },
  setElementText: (el, text) => {
    el.text = text;
    el.children = [];
  },
  setText: (el, text) => {
    el.text = text;
  },
  parentNode: (el) => el.parent ?? null,
  nextSibling: (el) =>
    el.parent?.children[el.parent.children.indexOf(el) + 1] ?? null,
});

let dispose = () => {};
afterEach(() => {
  dispose();
  setLocale("en");
  vi.unstubAllGlobals();
});
async function flush() {
  await Vue.nextTick();
  await Vue.nextTick();
}
async function mountedEditor(kind: "classes" | "tags") {
  const pinia = createPinia();
  setActivePinia(pinia);
  const store = useProject(pinia);
  store.meta = {
    id: "p",
    session: "one",
    root: "/tmp/p",
    image_count: 0,
    classes: [
      { id: "cat", index: 0, name: "cat", color: "#ff0000" },
      { id: "dog", index: 1, name: "dog", color: "#00ff00" },
    ],
    tags: [
      { id: "night", name: "night", color: "#0000ff" },
      { id: "sunny", name: "sunny", color: "#ffff00" },
    ],
  };
  const root = node("root");
  const editor = { ...CategoryEditor, render } as typeof CategoryEditor;
  const app = renderer.createApp({
    render: () =>
      Vue.h(editor, {
        category: store.meta![kind][0],
        onSaved: store.applyCategory,
        onError: (message: string) => {
          store.error = message;
        },
      }),
  });
  app.provide(Vue.ssrContextKey, { modules: new Set() });
  app.use(pinia);
  app.mount(root);
  dispose = () => app.unmount();
  await flush();
  const walk = (el: Node): Node[] => [el, ...el.children.flatMap(walk)];
  const inputs = () => walk(root).filter((el) => el.type === "input");
  const palette = () => store.meta![kind];
  const original = { ...palette()[0] };
  const draft = (name: string, color = original.color) => {
    inputs()[0].props["onUpdate:modelValue"](color);
    inputs()[1].props["onUpdate:modelValue"](name);
  };
  let resolve!: (response: Response) => void;
  const fetch = vi.fn().mockImplementation(
    () =>
      new Promise<Response>((done) => {
        resolve = done;
      }),
  );
  vi.stubGlobal("fetch", fetch);
  return {
    store,
    inputs,
    palette,
    original,
    draft,
    fetch,
    settle: (body: any, status = 200) =>
      resolve(new Response(JSON.stringify(body), { status })),
  };
}

it.each(["classes", "tags"] as const)(
  "keeps committed %s unchanged during editing and restores duplicate/empty names on rejection",
  async (kind) => {
    const ui = await mountedEditor(kind);
    const originalNames = ui.palette().map((c) => c.name);
    for (const name of [ui.palette()[1].name, "   "]) {
      ui.draft(name, "#123456");
      await flush();
      expect(ui.palette().map((c) => c.name)).toEqual(originalNames);
      const pending = ui.inputs()[1].props.onChange();
      await flush();
      expect(ui.inputs().every((el) => el.props.disabled)).toBe(true);
      ui.settle({ detail: "Name already exists" }, 400);
      await pending;
      await flush();
      expect(ui.palette().map((c) => c.name)).toEqual(originalNames);
      expect(ui.palette()[0]).toEqual(ui.original);
      expect(ui.inputs()[1].value).toBe(ui.original.name);
      expect(ui.inputs()[0].value).toBe(ui.original.color);
      expect(ui.inputs().every((el) => !el.props.disabled)).toBe(true);
      expect(ui.store.error).toContain("Name already exists");
    }
  },
);

it.each(["classes", "tags"] as const)(
  "commits canonical %s only after a successful response",
  async (kind) => {
    const ui = await mountedEditor(kind);
    ui.draft("  renamed  ", "#123456");
    const pending = ui.inputs()[1].props.onChange();
    await flush();
    expect(ui.palette()[0]).toEqual(ui.original);
    expect(ui.fetch).toHaveBeenCalledTimes(1);
    expect(JSON.parse(ui.fetch.mock.calls[0][1].body)).toEqual({
      name: "  renamed  ",
      color: "#123456",
    });
    const confirmed = { ...ui.original, name: "renamed", color: "#123456" };
    ui.settle(confirmed);
    await pending;
    await flush();
    expect(ui.palette()[0]).toEqual(confirmed);
    expect(ui.inputs()[1].value).toBe("renamed");
    expect(ui.inputs()[0].value).toBe("#123456");
    expect(ui.inputs().every((el) => !el.props.disabled)).toBe(true);
  },
);

it("rolls back a rejected color edit without polluting the class palette", async () => {
  const ui = await mountedEditor("classes");
  ui.draft(ui.original.name, "#123456");
  const pending = ui.inputs()[0].props.onChange();
  ui.settle({ detail: "Disk write failed" }, 500);
  await pending;
  await flush();
  expect(ui.palette()[0]).toEqual(ui.original);
  expect(ui.inputs()[0].value).toBe(ui.original.color);
});

it.each([200, 400])(
  "ignores a late %s response after switching projects with copied category UUIDs",
  async (status) => {
    const ui = await mountedEditor("classes");
    ui.draft("old-project-rename");
    const pending = ui.inputs()[1].props.onChange();
    ui.store.meta = {
      ...ui.store.meta!,
      session: "two",
      classes: ui
        .palette()
        .map((c) => ({ ...c, name: c.name + "-new-project" })),
    };
    await flush();
    ui.settle(
      status === 200
        ? { ...ui.original, name: "old-project-rename" }
        : { detail: "Old failure" },
      status,
    );
    await pending;
    await flush();
    expect(ui.palette()[0].name).toBe("cat-new-project");
    expect(ui.inputs()[1].value).toBe("cat-new-project");
    expect(ui.store.error).toBe("");
  },
);

it.each(["classes", "tags"] as const)(
  "keeps %s drafts independent while switching languages",
  async (kind) => {
    const ui = await mountedEditor(kind);
    ui.draft("unsaved draft");
    setLocale("zh-CN");
    await flush();
    expect(ui.inputs()[1].props["aria-label"]).toBe(
      kind === "classes" ? "类别名称" : "标签名称",
    );
    expect(ui.inputs()[1].value).toBe("unsaved draft");
    expect(ui.palette()[0]).toEqual(ui.original);
    setLocale("en");
    await flush();
    expect(ui.inputs()[1].props["aria-label"]).toBe(
      kind === "classes" ? "Class name" : "Tag name",
    );
    expect(ui.inputs()[1].value).toBe("unsaved draft");
  },
);
