import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { instance, request, type Annotation, type ProjectMeta } from "../api";
import { useProject } from "./project";
vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  request: vi.fn(),
}));
const mock = vi.mocked(request);
function ann(): Annotation {
  return {
    revision: 0,
    instances: [instance("c", [1, 1, 8, 8])],
    detection_review: "ok",
    segmentation_review: "ok",
    excluded: false,
    tags: [],
    notes: "",
    explicit_empty: {},
    width: 10,
    height: 10,
  };
}
function metadata(id = "p"): ProjectMeta {
  return {
    id,
    root: "/tmp/" + id,
    classes: [{ id: id + "c", index: 0, name: "Object", color: "#26835d" }],
    tags: [],
    image_count: 2,
  };
}
function initialized() {
  const s = useProject();
  s.meta = metadata();
  s.current = { id: "a", path: "a.png" };
  s.annotation = ann();
  s.images = [s.current, { id: "b", path: "b.png" }];
  return s;
}
function deferred<T>() {
  let resolve!: (v: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}
beforeEach(() => {
  setActivePinia(createPinia());
  mock.mockReset();
  vi.useFakeTimers();
});
afterEach(() => {
  vi.clearAllTimers();
  vi.useRealTimers();
});
describe("annotation concurrency", () => {
  it("does not apply image A inference to image B", async () => {
    const s = initialized(),
      pending = deferred<Annotation>();
    mock.mockImplementation(async (path) =>
      path.endsWith("/segment") ? await pending.promise : ann(),
    );
    const run = s.segment();
    await Promise.resolve();
    await Promise.resolve();
    await s.load(s.images[1]);
    const before = JSON.stringify(s.annotation);
    pending.resolve({ ...ann(), instances: [], revision: 1 });
    await run;
    expect(s.current?.id).toBe("b");
    expect(JSON.stringify(s.annotation)).toBe(before);
  });
  it("preserves edits made while inference was in flight", async () => {
    const s = initialized(),
      pending = deferred<Annotation>();
    mock.mockImplementation(async (path) =>
      path.endsWith("/segment") ? await pending.promise : ann(),
    );
    const run = s.segment();
    await Promise.resolve();
    await Promise.resolve();
    s.annotation!.notes = "new notes";
    s.changed();
    pending.resolve({ ...ann(), notes: "old notes", revision: 1 });
    await run;
    expect(s.annotation!.notes).toBe("new notes");
  });
  it("flushes outgoing edits again before replacing after navigation GET", async () => {
    const s = initialized(),
      pending = deferred<Annotation>();
    mock.mockImplementation(async (path, method) =>
      method === "PUT" ? { ...ann(), revision: 1 } : await pending.promise,
    );
    const load = s.load(s.images[1]);
    await Promise.resolve();
    await Promise.resolve();
    s.annotation!.notes = "late outgoing edit";
    s.changed();
    pending.resolve(ann());
    await load;
    expect(
      mock.mock.calls.some(
        ([path, method, body]) =>
          path === "/images/a/annotation" &&
          method === "PUT" &&
          (body as Annotation).notes === "late outgoing edit",
      ),
    ).toBe(true);
  });
  it("invalidates both approved tasks when a shared class changes", () => {
    const s = initialized();
    s.selected = s.annotation!.instances[0].id;
    s.assign("new");
    expect(s.annotation!.detection_review).toBe("pending");
    expect(s.annotation!.segmentation_review).toBe("pending");
  });
  it("resets the default class when the project changes", async () => {
    const s = initialized();
    s.defaultClass = "old";
    mock.mockImplementation(async (path) =>
      path === "/project"
        ? metadata("new")
        : path.startsWith("/images?")
          ? { items: [], total: 0 }
          : {},
    );
    await s.open("/new");
    expect(s.defaultClass).toBe("newc");
  });
});

describe("startup and model configuration", () => {
  it("handles a server with no open project", async () => {
    const s = initialized();
    mock.mockResolvedValue(null);
    await s.refresh();
    expect(s.meta).toBeNull();
    expect(s.current).toBeNull();
    expect(s.images).toEqual([]);
    expect(mock).toHaveBeenCalledTimes(1);
  });
  it("loads model IDs from the server and preserves a valid selection", async () => {
    const s = useProject();
    const models = {
      config: "/models.json",
      default_model: "small",
      models: [
        {
          id: "small",
          name: "Small",
          backend: "sam2",
          available: true,
          path: "/small.pt",
          error: null,
          text_prompts: false,
        },
        {
          id: "mobile",
          name: "Mobile",
          backend: "mobile_sam",
          available: false,
          path: null,
          error: "missing",
          text_prompts: false,
        },
      ],
    };
    mock.mockResolvedValue(models);
    await s.refreshModels();
    expect(s.model).toBe("small");
    s.model = "mobile";
    await s.refreshModels();
    expect(s.model).toBe("mobile");
    expect(s.models?.models[1].available).toBe(false);
  });
});

describe("quick class assignment", () => {
  it("changes only the selected annotation and remains undoable", () => {
    const s = initialized();
    const geometry = JSON.stringify(s.annotation!.instances[0].box);
    s.selected = s.annotation!.instances[0].id;
    s.openClassPicker();
    expect(s.classPickerOpen).toBe(true);
    s.assign("another-class");
    expect(s.object?.class_id).toBe("another-class");
    expect(JSON.stringify(s.object?.box)).toBe(geometry);
    s.undo();
    expect(s.annotation!.instances[0].class_id).toBe("c");
  });
  it("does not change a locked instance or open the picker", () => {
    const s = initialized();
    s.selected = s.annotation!.instances[0].id;
    s.annotation!.instances[0].locked = true;
    s.openClassPicker();
    s.assign("another-class");
    expect(s.classPickerOpen).toBe(false);
    expect(s.object?.class_id).toBe("c");
    expect(s.dirty).toBe(false);
  });
});

describe("assisted annotation", () => {
  it("changes detection geometry without clearing segmentation review", () => {
    const s = initialized();
    s.annotation!.instances[0].box = [1, 1, 9, 9];
    s.changed("detection");
    expect(s.annotation!.detection_review).toBe("pending");
    expect(s.annotation!.segmentation_review).toBe("ok");
  });
  it("does not apply a late detection result to another image", async () => {
    const s = initialized(),
      pending = deferred<Annotation>();
    s.detectionModel = "det";
    mock.mockImplementation(async (path) =>
      path.endsWith("/detect") ? pending.promise : ann(),
    );
    const run = s.detect();
    await Promise.resolve();
    await Promise.resolve();
    await s.load(s.images[1]);
    pending.resolve({ ...ann(), instances: [], revision: 1 });
    await run;
    expect(s.current?.id).toBe("b");
    expect(s.annotation!.instances).toHaveLength(1);
  });
  it("preserves local edits made during mask-to-box processing", async () => {
    const s = initialized(),
      pending = deferred<Annotation>();
    mock.mockImplementation(async (path) =>
      path.endsWith("/boxes-from-masks") ? pending.promise : ann(),
    );
    const run = s.boxesFromMasks();
    await Promise.resolve();
    await Promise.resolve();
    s.annotation!.notes = "new human notes";
    s.changed();
    pending.resolve({ ...ann(), notes: "old", revision: 1 });
    await run;
    expect(s.annotation!.notes).toBe("new human notes");
    expect(s.error).toContain("newer edits");
  });
});
