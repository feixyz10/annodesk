import source from "./ModelSettings.vue?raw";
import { transpile } from "typescript";
import { afterEach, expect, it, vi } from "vitest";
import * as Vue from "vue";
import { compile } from "@vue/compiler-dom";
import { compileScript, parse } from "@vue/compiler-sfc";
import { createPinia, setActivePinia } from "pinia";
import { useProject } from "../stores/project";
import ModelSettings from "./ModelSettings.vue";
vi.mock("naive-ui", async () => {
  const { h } = await import("vue");
  return {
    NModal: (props: any, { slots }: any) =>
      props.show ? h("div", slots.default?.()) : null,
  };
});
vi.mock("./ModelNotice.vue", () => ({ default: { render: () => null } }));
const { descriptor } = parse(source);
const bindings = compileScript(descriptor, {
  id: "model-settings-test",
}).bindings;
const { code } = compile(descriptor.template!.content, {
  mode: "function",
  prefixIdentifiers: true,
  bindingMetadata: bindings,
});
const render = new Function("Vue", transpile(code))({
  ...Vue,
  vModelText: {},
  vModelSelect: {},
  vModelCheckbox: {},
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
  vi.unstubAllGlobals();
});
function all(root: Node): Node[] {
  return [root, ...root.children.flatMap(all)];
}
function content(root: Node): string {
  return root.text + root.children.map(content).join("");
}
async function flush() {
  await new Promise((resolve) => setTimeout(resolve, 0));
  await Vue.nextTick();
}
it.each(["unchanged", "replaced", "removed"])(
  "reload invalidates compatibility and reconciles selection: %s",
  async (variant) => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const store = useProject(pinia);
    store.meta = {
      id: "p",
      session: "one",
      root: "/tmp/p",
      image_count: 0,
      classes: [],
      tags: [],
    };
    store.task = "detection";
    let ids = ["a"];
    const bodies: any[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url.endsWith("/models/check")) {
          const body = JSON.parse(String(init?.body));
          bodies.push(body);
          return new Response(
            JSON.stringify({
              model: body.model,
              class_names: { 0: "cat" },
              compatibility: {
                relation: "equal",
                accepted_classes: 1,
                extra_classes: [],
              },
            }),
          );
        }
        return new Response(
          JSON.stringify({
            config: "models.json",
            default_model: "",
            default_detection_model: ids[0] || "",
            models: ids.map((id) => ({
              id,
              name: id,
              task: "detection",
              backend: "ultralytics",
              available: true,
              text_prompts: false,
              path: null,
              error: null,
            })),
          }),
        );
      }),
    );
    const root = node("root"),
      show = Vue.ref(false);
    const component = { ...ModelSettings, render } as typeof ModelSettings;
    const app = renderer.createApp({
      render: () => Vue.h(component, { show: show.value }),
    });
    app.use(pinia);
    app.provide(Vue.ssrContextKey, { modules: new Set() });
    app.mount(root);
    dispose = () => app.unmount();
    show.value = true;
    await flush();
    const button = (text: string) =>
      all(root).find((n) => n.type === "button" && content(n).trim() === text)!;
    const confidence = all(root).find(
      (n) => n.type === "input" && n.props.step === "0.05",
    )!;
    confidence.props["onUpdate:modelValue"](0.65);
    await button("Check classes").props.onClick();
    await flush();
    expect(content(root)).toContain("Compatible");
    ids = variant === "replaced" ? ["b"] : variant === "removed" ? [] : ["a"];
    await button("Reload configuration").props.onClick();
    await flush();
    expect(content(root)).not.toContain("Compatible");
    if (variant === "removed") {
      expect(button("Check classes").props.disabled).toBe(true);
    } else {
      expect(button("Check classes").props.disabled).toBe(false);
      await button("Check classes").props.onClick();
      await flush();
      expect(bodies.at(-1).model).toBe(ids[0]);
      expect(bodies.at(-1).confidence).toBe(
        variant === "unchanged" ? 0.65 : 0.25,
      );
    }
  },
);
