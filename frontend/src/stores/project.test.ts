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

describe("mask candidates", () => {
  function ready() {
    const s = initialized();
    s.model = "sam";
    s.selected = s.annotation!.instances[0].id;
    s.models = {
      config: "/models.json",
      default_model: "sam",
      models: [
        {
          id: "sam",
          name: "SAM",
          backend: "sam2",
          task: "segmentation",
          available: true,
          path: "/model",
          error: null,
          text_prompts: false,
          mask_candidates: true,
        },
      ],
    };
    return s;
  }
  function proposal(
    s: ReturnType<typeof useProject>,
    revision = s.annotation!.revision,
  ) {
    return {
      project_id: "p",
      image_id: "a",
      instance_id: s.selected!,
      revision,
      image_stamp: "1790000000000000000:42",
      model: "sam",
      items: [
        {
          mask: { size: [10, 10], counts: "first" },
          polygons: [],
          quality: 0.96,
          overlay: "data:image/png;base64,first",
        },
        {
          mask: { size: [10, 10], counts: "second" },
          polygons: [],
          quality: 0.85,
          overlay: "data:image/png;base64,second",
        },
      ],
    };
  }
  async function flush() {
    for (let i = 0; i < 12; i++) await Promise.resolve();
  }
  it("keeps proposals transient and sends only the selected mask on Apply", async () => {
    const s = ready(),
      original = JSON.stringify(s.annotation);
    mock.mockImplementation(async (path, method, body) => {
      if (path.endsWith("/mask-candidates")) return proposal(s);
      if (path.endsWith("/apply"))
        return {
          ...s.annotation!,
          revision: 1,
          segmentation_review: "pending",
          instances: [
            { ...s.object!, mask: (body as any).mask, source: "sam" },
          ],
        };
      return ann();
    });
    await s.generateCandidates();
    expect(s.candidates?.phase).toBe("ready");
    expect(JSON.stringify(s.annotation)).toBe(original);
    expect(s.dirty).toBe(false);
    expect(s.history).toHaveLength(0);
    s.candidates!.active = 1;
    const expected = s.candidate!.mask;
    await s.applyCandidate();
    expect(
      mock.mock.calls.find(([path]) => path.endsWith("/apply"))?.[2],
    ).toMatchObject({ mask: expected });
    expect(
      mock.mock.calls.find(([path]) => path.endsWith("/apply"))?.[2],
    ).not.toHaveProperty("items");
    expect(s.object?.mask).toEqual(expected);
    expect(s.annotation!.detection_review).toBe("ok");
    expect(s.candidates).toBeNull();
    s.undo();
    expect(s.annotation!.instances[0].mask).toBeNull();
    expect(s.annotation!.detection_review).toBe("ok");
  });
  it("ignores a late response after navigation and reports discarded preview", async () => {
    const s = ready(),
      pending = deferred<ReturnType<typeof proposal>>(),
      response = proposal(s);
    mock.mockImplementation(async (path) =>
      path.endsWith("/mask-candidates") ? pending.promise : ann(),
    );
    const run = s.generateCandidates();
    await flush();
    await s.load(s.images[1]);
    pending.resolve(response);
    await run;
    expect(s.current?.id).toBe("b");
    expect(s.candidates).toBeNull();
    expect(s.candidateNotice).toContain("discarded");
    expect(s.annotation!.instances[0].mask).toBeNull();
  });
  it("coalesces prompt edits during inference and regenerates from saved prompts", async () => {
    const s = ready(),
      pending = deferred<ReturnType<typeof proposal>>(),
      first = proposal(s);
    let calls = 0;
    mock.mockImplementation(async (path, method, body) => {
      if (method === "PUT")
        return {
          ...(body as Annotation),
          revision: s.annotation!.revision + 1,
        };
      if (path.endsWith("/mask-candidates")) {
        calls++;
        return calls === 1
          ? pending.promise
          : proposal(s, (body as any).expected_revision);
      }
      return ann();
    });
    const run = s.generateCandidates();
    await flush();
    for (let i = 0; i < 3; i++) {
      s.object!.points.push({ x: i + 1, y: 2, positive: true });
      s.changed("segmentation");
      await vi.advanceTimersByTimeAsync(500);
    }
    expect(calls).toBe(1);
    pending.resolve(first);
    await run;
    await flush();
    expect(calls).toBe(2);
    expect(s.candidates?.phase).toBe("ready");
    expect(s.candidates?.response?.revision).toBe(s.annotation!.revision);
  });
  it("cancels on annotation or model changes but tolerates unchanged metadata refreshes", async () => {
    const s = ready();
    mock.mockImplementation(async () => proposal(s));
    await s.generateCandidates();
    s.meta = JSON.parse(JSON.stringify(s.meta));
    await flush();
    expect(s.candidates?.phase).toBe("ready");
    s.annotation!.notes = "human edit";
    s.changed();
    await flush();
    expect(s.candidates).toBeNull();
    s.dirty = false;
    await s.generateCandidates();
    s.model = "other";
    expect(s.candidates).toBeNull();
  });
  it("does not replace existing masks on a failed Apply", async () => {
    const s = ready();
    const original = JSON.stringify(s.annotation);
    mock.mockImplementation(async (path) => {
      if (path.endsWith("/apply")) throw new Error("Revision conflict");
      return proposal(s);
    });
    await s.generateCandidates();
    await s.applyCandidate();
    expect(s.candidates?.phase).toBe("error");
    expect(JSON.stringify(s.annotation)).toBe(original);
    expect(s.history).toHaveLength(0);
  });
});
