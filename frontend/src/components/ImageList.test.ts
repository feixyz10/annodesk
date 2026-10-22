import source from "./ImageList.vue?raw";
import { transpile } from "typescript";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as Vue from "vue";
import { compile } from "@vue/compiler-dom";
import { compileScript, parse } from "@vue/compiler-sfc";
import { createPinia, setActivePinia } from "pinia";
import { setLocale } from "../i18n";
import { useProject } from "../stores/project";
import ImageList from "./ImageList.vue";

// Exercise the actual SFC template and setup with a small Vue host renderer.
// Native input directives are irrelevant: tests drive the real store/control bindings.
const { descriptor } = parse(source);
const bindings = compileScript(descriptor, { id: "image-list-test" }).bindings;
const { code } = compile(descriptor.template!.content, {
  mode: "function",
  prefixIdentifiers: true,
  bindingMetadata: bindings,
});
const render = new Function("Vue", transpile(code))({
  ...Vue,
  vModelText: {},
  vModelSelect: {},
});
interface Node {
  type: string;
  children: Node[];
  parent?: Node;
  props: Record<string, any>;
  text: string;
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
  vi.restoreAllMocks();
});
async function mountedList(nested = false) {
  const pinia = createPinia();
  setActivePinia(pinia);
  const store = useProject(pinia);
  store.meta = {
    id: "project",
    session: "session-a",
    root: "/tmp/a",
    classes: [],
    tags: [],
    image_count: 1000,
  };
  store.images = Array.from({ length: 1000 }, (_, i) => ({
    id: String(i),
    path: (nested ? "folder/" : "") + `image-${i}.png`,
  }));
  const root = node("root");
  const app = renderer.createApp({ ...ImageList, render });
  app.provide(Vue.ssrContextKey, { modules: new Set() });
  app.use(pinia);
  app.mount(root);
  dispose = () => app.unmount();
  await Vue.nextTick();
  const elements = (): Node[] => {
    const walk = (el: Node): Node[] => [el, ...el.children.flatMap(walk)];
    return walk(root);
  };
  const list = () => elements().find((el) => el.props.class === "file-list")!;
  const buttons = () => list().children.filter((el) => el.type === "button");
  const topSpace = () =>
    list().children.find((el) => el.type === "div")!.props.style.height;
  async function scrollTo(value: number) {
    list().scrollTop = value;
    list().props.onScroll({ target: list() });
    await Vue.nextTick();
  }
  async function clickText(text: string) {
    elements()
      .find((el) => el.type === "button" && el.text === text)!
      .props.onClick();
    await Vue.nextTick();
  }
  return { store, elements, list, buttons, topSpace, scrollTo, clickText };
}

describe("image list virtualization", () => {
  it.each(["en", "zh-CN"])(
    "shows a unique search result after deep scrolling (%s)",
    async (language) => {
      setLocale(language);
      const ui = await mountedList();
      await ui.scrollTo(20000);
      expect(ui.topSpace()).not.toBe("0px");
      ui.store.search = "image-999.png";
      await Vue.nextTick();
      expect(ui.store.filtered).toHaveLength(1);
      expect(ui.buttons()).toHaveLength(1);
      expect(ui.buttons()[0].props.title).toBe("image-999.png");
      expect(ui.list().scrollTop).toBe(0);
      expect(ui.topSpace()).toBe("0px");
      ui.store.search = "no-match";
      await Vue.nextTick();
      expect(ui.buttons()).toHaveLength(0);
      expect(ui.topSpace()).toBe("0px");
    },
  );

  it("resets on folder collapse/expand and tree/flat changes", async () => {
    const ui = await mountedList(true);
    await ui.clickText("Expand all");
    await ui.scrollTo(20000);
    await ui.clickText("Collapse all");
    expect(ui.buttons()).toHaveLength(1);
    expect(ui.list().scrollTop).toBe(0);
    expect(ui.topSpace()).toBe("0px");
    // Open the remaining folder row, then change display mode at a deep offset.
    ui.buttons()[0].props.onClick();
    await Vue.nextTick();
    expect(ui.buttons()).toHaveLength(40);
    await ui.scrollTo(20000);
    ui.elements()
      .find((el) => el.type === "select")!
      .props["onUpdate:modelValue"](false);
    await Vue.nextTick();
    expect(ui.list().scrollTop).toBe(0);
    expect(ui.topSpace()).toBe("0px");
    expect(ui.buttons()[0].props.title).toBe("folder/image-0.png");
  });

  it("preserves scroll and open folders during a same-session metadata refresh", async () => {
    const ui = await mountedList(true);
    await ui.clickText("Expand all");
    await ui.scrollTo(20000);
    ui.store.meta = { ...ui.store.meta!, image_count: 1001 };
    await Vue.nextTick();
    expect(ui.list().scrollTop).toBe(20000);
    expect(ui.topSpace()).not.toBe("0px");
    expect(ui.buttons()).toHaveLength(40);
  });

  it("clamps the window when data shrinks without changing the search", async () => {
    const ui = await mountedList();
    await ui.scrollTo(20000);
    ui.store.images = ui.store.images.slice(0, 2);
    await Vue.nextTick();
    expect(ui.buttons()).toHaveLength(2);
    expect(ui.list().scrollTop).toBe(0);
    expect(ui.topSpace()).toBe("0px");
  });

  it("resets scroll and folder state when a new session opens a copied project", async () => {
    const ui = await mountedList(true);
    await ui.clickText("Expand all");
    await ui.scrollTo(20000);
    ui.store.meta = { ...ui.store.meta!, session: "session-b" };
    await Vue.nextTick();
    expect(ui.list().scrollTop).toBe(0);
    expect(ui.topSpace()).toBe("0px");
    expect(ui.buttons()).toHaveLength(1);
    expect(ui.buttons()[0].props.title).toBe("folder");
  });
});
