import source from "./FilmStrip.vue?raw";
import { transpile } from "typescript";
import { afterEach, describe, expect, it, vi } from "vitest";
import * as Vue from "vue";
import { compile } from "@vue/compiler-dom";
import { compileScript, parse } from "@vue/compiler-sfc";
import { createPinia, setActivePinia } from "pinia";
import { setLocale } from "../i18n";
import { useProject } from "../stores/project";
import FilmStrip from "./FilmStrip.vue";

// Test the actual SFC template and state, with no thumbnail network/decoder side effects.
vi.mock("./ThumbImage.vue", () => ({
  default: { props: ["id"], render: () => null },
}));
const { descriptor } = parse(source);
const bindings = compileScript(descriptor, { id: "film-strip-test" }).bindings;
const { code } = compile(descriptor.template!.content, {
  mode: "function",
  prefixIdentifiers: true,
  bindingMetadata: bindings,
});
const render = new Function("Vue", transpile(code))(Vue);
interface Node {
  type: string;
  children: Node[];
  parent?: Node;
  props: Record<string, any>;
  text: string;
  scrollLeft: number;
  clientWidth: number;
}
function node(type: string): Node {
  return {
    type,
    children: [],
    props: {},
    text: "",
    scrollLeft: 0,
    clientWidth: 600,
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
});
async function flush() {
  await Vue.nextTick();
  await Vue.nextTick();
}
async function mountedStrip() {
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
    path: `image-${i}.png`,
  }));
  const root = node("root");
  const app = renderer.createApp({ ...FilmStrip, render });
  app.provide(Vue.ssrContextKey, { modules: new Set() });
  app.use(pinia);
  app.mount(root);
  dispose = () => app.unmount();
  await flush();
  const walk = (el: Node): Node[] => [el, ...el.children.flatMap(walk)];
  const strip = () => walk(root).find((el) => el.props.class === "film")!;
  const buttons = () => strip().children.filter((el) => el.type === "button");
  const leftSpace = () =>
    strip().children.find((el) => el.type === "span")!.props.style.width;
  async function scrollTo(value: number) {
    strip().scrollLeft = value;
    strip().props.onScroll();
    await flush();
  }
  return { store, strip, buttons, leftSpace, scrollTo };
}

describe("film strip virtualization", () => {
  it.each(["en", "zh-CN"])(
    "renders a unique match after scrolling 60000px (%s)",
    async (language) => {
      setLocale(language);
      const ui = await mountedStrip();
      await ui.scrollTo(60000);
      expect(ui.buttons()).toHaveLength(18);
      expect(ui.leftSpace()).not.toBe("0px");
      ui.store.search = "image-999.png";
      await flush();
      expect(ui.store.filtered).toHaveLength(1);
      expect(ui.buttons()).toHaveLength(1);
      expect(ui.buttons()[0].props.title).toBe("image-999.png");
      expect(ui.strip().scrollLeft).toBe(0);
      expect(ui.leftSpace()).toBe("0px");
      ui.store.search = "no-match";
      await flush();
      expect(ui.buttons()).toHaveLength(0);
      expect(ui.leftSpace()).toBe("0px");
    },
  );

  it("clamps the start and real offset when the image set shrinks", async () => {
    const ui = await mountedStrip();
    await ui.scrollTo(60000);
    ui.store.images = ui.store.images.slice(0, 2);
    await flush();
    expect(ui.buttons()).toHaveLength(2);
    expect(ui.strip().scrollLeft).toBe(0);
    expect(ui.leftSpace()).toBe("0px");
  });

  it("resets for a copied project's new session but preserves manual scroll on metadata refresh", async () => {
    const ui = await mountedStrip();
    await ui.scrollTo(60000);
    ui.store.meta = { ...ui.store.meta!, image_count: 1001 };
    await flush();
    expect(ui.strip().scrollLeft).toBe(60000);
    ui.store.meta = { ...ui.store.meta!, session: "session-b" };
    await flush();
    expect(ui.strip().scrollLeft).toBe(0);
    expect(ui.leftSpace()).toBe("0px");
    expect(ui.buttons()[0].props.title).toBe("image-0.png");
  });

  it("keeps navigation centering and the rendered window in sync", async () => {
    const ui = await mountedStrip();
    ui.store.current = ui.store.images[900];
    await flush();
    expect(ui.strip().scrollLeft).toBeGreaterThan(100000);
    expect(ui.buttons().some((el) => el.props.title === "image-900.png")).toBe(
      true,
    );
    expect(ui.buttons()).toHaveLength(18);
    // A pending navigation callback must not restore the old offset after filtering.
    ui.store.current = ui.store.images[901];
    ui.store.search = "image-1.png";
    await flush();
    expect(ui.buttons()).toHaveLength(1);
    expect(ui.buttons()[0].props.title).toBe("image-1.png");
    expect(ui.strip().scrollLeft).toBe(0);
    expect(ui.leftSpace()).toBe("0px");
  });
});
