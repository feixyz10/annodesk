import { afterEach, describe, expect, it, vi } from "vitest";
import { createRenderer, h, nextTick, ssrContextKey } from "vue";
import { createPinia, setActivePinia } from "pinia";
import { instance } from "../api";
import { useProject } from "../stores/project";
import AnnotationCanvas from "./AnnotationCanvas.vue";

const graph = vi.hoisted(() => ({ layers: [] as any[], stages: [] as any[] }));
vi.mock("konva", () => {
  class Node {
    children: Node[] = [];
    constructor(public attrs: any = {}) {}
    add(child: Node) {
      this.children.push(child);
    }
    destroyChildren() {
      this.children = [];
    }
    destroyed = false;
    destroy() {
      this.destroyed = true;
    }
    x() {
      return this.attrs.x ?? 0;
    }
    y() {
      return this.attrs.y ?? 0;
    }
    setAttrs(attrs: any) {
      Object.assign(this.attrs, attrs);
    }
    getPointerPosition() {
      return this.attrs.pointer ?? { x: 1, y: 1 };
    }
    getAbsoluteTransform() {
      return {
        copy: () => ({ invert: () => ({ point: (point: any) => point }) }),
      };
    }
    handlers: Record<string, (...args: any[]) => void> = {};
    on(events: string, handler: (...args: any[]) => void) {
      for (const event of events.split(" ")) this.handlers[event] = handler;
    }
    draggable(value: boolean) {
      this.attrs.draggable = value;
    }
    batchDraw() {}
    width() {
      return this.attrs.width ?? 640;
    }
    height() {
      return this.attrs.height ?? 480;
    }
    scale() {}
    scaleX() {
      return 1;
    }
    position() {}
  }
  class Stage extends Node {
    constructor(attrs: any) {
      super(attrs);
      graph.stages.push(this);
    }
  }
  class Layer extends Node {
    constructor() {
      super();
      graph.layers.push(this);
    }
  }
  return {
    default: {
      Stage,
      Layer,
      Image: Node,
      Line: Node,
      Rect: Node,
      Circle: Node,
      Transformer: Node,
    },
  };
});

class ImageRequest {
  static requests: ImageRequest[] = [];
  src = "";
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor() {
    ImageRequest.requests.push(this);
  }
  async decode() {}
}
const renderer = createRenderer<any, any>({
  createElement: () => ({ clientWidth: 640, clientHeight: 480 }),
  insert() {},
  remove() {},
  patchProp() {},
  setElementText() {},
  createText: () => ({}),
  createComment: () => ({}),
  setText() {},
  parentNode: () => null,
  nextSibling: () => null,
});
let dispose = () => {};
afterEach(() => {
  dispose();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
async function flush() {
  await nextTick();
  await nextTick();
}
async function mountedCanvas() {
  graph.layers = [];
  graph.stages = [];
  ImageRequest.requests = [];
  vi.stubGlobal("Image", ImageRequest);
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
  vi.stubGlobal("window", {
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  });
  const pinia = createPinia();
  setActivePinia(pinia);
  const store = useProject(pinia);
  store.meta = {
    id: "p",
    root: "/tmp/p",
    classes: [],
    tags: [],
    image_count: 2,
  };
  store.current = { id: "a", path: "a.png" };
  const obj = instance(null);
  obj.id = "object";
  obj.mask = { size: [10, 10], counts: "test" };
  store.annotation = {
    revision: 0,
    instances: [obj],
    detection_review: "ok",
    segmentation_review: "ok",
    excluded: false,
    tags: [],
    notes: "",
    explicit_empty: {},
    width: 10,
    height: 10,
  };
  // Vitest transforms SFCs for SSR in Node. Supply the one-div host template
  // to the custom renderer; all canvas lifecycle/render logic is the real SFC.
  const canvas = {
    ...AnnotationCanvas,
    render: () => h("div", { ref: "host" }),
  };
  const app = renderer.createApp({ render: () => h(canvas) });
  app.provide(ssrContextKey, { modules: new Set() });
  app.use(pinia);
  app.mount({});
  dispose = () => app.unmount();
  await flush();
  return store;
}
function masks() {
  return ImageRequest.requests.filter((r) => r.src.includes("/masks/"));
}
function rendered(image: ImageRequest) {
  return graph.layers
    .at(-1)
    .children.some((node: any) => node.attrs.image === image);
}

describe("mask overlay lifecycle", () => {
  it("evicts completed overlays from earlier revisions", async () => {
    const store = await mountedCanvas();
    const first = masks().at(-1)!;
    first.onload!();
    expect(rendered(first)).toBe(true);
    store.annotation!.revision = 1;
    await flush();
    masks().at(-1)!.onload!();
    store.annotation!.revision = 0;
    await flush();
    expect(masks()).toHaveLength(3);
    expect(rendered(first)).toBe(false);
  });
  it("reloads a same-ID image in a new project and drops previous project responses", async () => {
    const store = await mountedCanvas();
    const old = masks().at(-1)!;
    store.meta = { ...store.meta!, id: "other-project" };
    await flush();
    const latest = masks().at(-1)!;
    expect(latest).not.toBe(old);
    old.onload!();
    expect(rendered(old)).toBe(false);
    latest.onload!();
    expect(rendered(latest)).toBe(true);
  });
  it("rejects a late response after navigating away and back to the same image", async () => {
    const store = await mountedCanvas();
    const old = masks().at(-1)!;
    store.current = { id: "b", path: "b.png" };
    await flush();
    store.current = { id: "a", path: "a.png" };
    await flush();
    const latest = masks().at(-1)!;
    old.onload!();
    expect(rendered(old)).toBe(false);
    latest.onload!();
    expect(rendered(latest)).toBe(true);
    dispose();
    dispose = () => {};
    store.error = "";
    old.onerror!();
    expect(store.error).toBe("");
  });
});

describe("temporary Space panning", () => {
  it("disables box dragging, selection and transform handles until Space is released", async () => {
    const store = await mountedCanvas();
    store.annotation!.instances[0].box = [1, 2, 8, 9];
    store.tool = "select";
    store.selected = "object";
    await flush();
    const checkpoint = vi.spyOn(store, "checkpoint");
    const editBox = vi.spyOn(store, "editBox");
    const nodes = () => graph.layers.at(-1).children;
    const box = () => nodes().find((node: any) => node.attrs.width === 7);
    expect(box().attrs.draggable).toBe(true);
    expect(nodes().some((node: any) => node.attrs.nodes)).toBe(true);
    const handler = (name: string) =>
      vi
        .mocked(window.addEventListener)
        .mock.calls.find(([event]) => event === name)![1] as (
        event: any,
      ) => void;
    handler("keydown")({
      code: "Space",
      target: { closest: () => null },
      preventDefault() {},
    });
    expect(graph.stages.at(-1).attrs.draggable).toBe(true);
    expect(box().attrs.draggable).toBe(false);
    expect(nodes().some((node: any) => node.attrs.nodes)).toBe(false);
    store.selected = null;
    const event = { cancelBubble: false };
    box().handlers.mousedown(event);
    box().handlers.dragstart();
    box().handlers.dragend();
    box().handlers.transformstart();
    box().handlers.transformend();
    expect(event.cancelBubble).toBe(false);
    expect(store.selected).toBeNull();
    expect(checkpoint).not.toHaveBeenCalled();
    expect(editBox).not.toHaveBeenCalled();
    handler("keyup")({ code: "Space" });
    expect(graph.stages.at(-1).attrs.draggable).toBe(false);
    expect(box().attrs.draggable).toBe(true);
    expect(store.annotation!.instances[0].box).toEqual([1, 2, 8, 9]);
  });
});

function drawStart() {
  const stage = graph.stages.at(-1);
  stage.attrs.pointer = { x: 1, y: 1 };
  stage.handlers.mousedown({ target: stage });
  stage.attrs.pointer = { x: 8, y: 7 };
  stage.handlers.mousemove();
  return stage;
}
function annotationCopy(store: ReturnType<typeof useProject>) {
  return JSON.parse(JSON.stringify(store.annotation));
}
function mockSave(store: ReturnType<typeof useProject>) {
  const fetch = vi.fn().mockImplementation(
    async () =>
      new Response(
        JSON.stringify({
          ...store.annotation,
          revision: store.annotation!.revision + 1,
        }),
      ),
  );
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

describe("canvas gesture ownership", () => {
  it.each(["box", "promptbox"])(
    "saves a completed %s gesture to its original image",
    async (tool) => {
      const store = await mountedCanvas();
      store.tool = tool;
      await flush();
      const fetch = mockSave(store);
      const stage = drawStart();
      stage.handlers.mouseup();
      const obj = store.annotation!.instances.at(-1)!;
      expect(tool === "box" ? obj.box : obj.prompt_box).toEqual([1, 1, 8, 7]);
      expect(tool === "box" ? obj.prompt_box : obj.box).toBeNull();
      await store.save();
      expect(fetch).toHaveBeenCalledTimes(1);
      expect(fetch.mock.calls[0][0]).toContain("/images/a/annotation");
    },
  );

  it.each([
    "image",
    "image-roundtrip",
    "project-session",
    "project-root",
    "tool",
    "tool-roundtrip",
    "navigating",
    "annotation",
  ])(
    "cancels an unfinished rectangle on %s change before the next render",
    async (change) => {
      const store = await mountedCanvas();
      store.tool = "box";
      await flush();
      const fetch = mockSave(store);
      const checkpoint = vi.spyOn(store, "checkpoint");
      const changed = vi.spyOn(store, "changed");
      const stage = drawStart();
      const preview = graph.layers
        .at(-1)
        .children.find((n: any) => n.attrs.stroke === "#315fe9");
      expect(preview).toBeDefined();
      if (change === "image" || change === "image-roundtrip") {
        store.current = { id: "b", path: "b.png" };
        if (change === "image-roundtrip")
          store.current = { id: "a", path: "a.png" };
        else store.annotation = annotationCopy(store);
      } else if (change === "project-session")
        store.meta = { ...store.meta!, session: "new-session" };
      else if (change === "project-root")
        store.meta = { ...store.meta!, root: "/tmp/other" };
      else if (change === "tool" || change === "tool-roundtrip") {
        store.tool = "promptbox";
        if (change === "tool-roundtrip") store.tool = "box";
      } else if (change === "navigating") {
        store.navigating = true;
        store.navigating = false;
      } else store.annotation = annotationCopy(store);
      // No nextTick: mouseup may arrive before Vue's normal redraw watcher.
      const before = JSON.stringify(store.annotation);
      stage.handlers.mouseup();
      expect(preview.destroyed).toBe(true);
      expect(JSON.stringify(store.annotation)).toBe(before);
      expect(checkpoint).not.toHaveBeenCalled();
      expect(changed).not.toHaveBeenCalled();
      await store.save();
      expect(fetch).not.toHaveBeenCalled();
    },
  );

  it.each(["drag", "transform"])(
    "ignores a late %s end for a same-ID instance on a different image",
    async (event) => {
      const store = await mountedCanvas();
      store.annotation!.instances[0].box = [1, 1, 4, 4];
      store.tool = "select";
      await flush();
      const fetch = mockSave(store);
      const oldBox = graph.layers
        .at(-1)
        .children.find((n: any) => n.attrs.width === 3);
      oldBox.handlers[event + "start"]();
      const next = annotationCopy(store);
      next.instances[0].box = [2, 2, 5, 5];
      store.current = { id: "b", path: "b.png" };
      store.annotation = next;
      const edit = vi.spyOn(store, "editBox");
      oldBox.handlers[event + "end"]();
      expect(edit).not.toHaveBeenCalled();
      expect(store.annotation!.instances[0].box).toEqual([2, 2, 5, 5]);
      await store.save();
      expect(fetch).not.toHaveBeenCalled();
    },
  );
});
