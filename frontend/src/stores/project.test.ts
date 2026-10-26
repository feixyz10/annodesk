import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { instance, request, type Annotation, type ProjectMeta } from "../api";
import { useProject } from "./project";
import { setLocale } from "../i18n";
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
  setLocale("en");
  setActivePinia(createPinia());
  mock.mockReset();
  vi.useFakeTimers();
});
afterEach(() => {
  setLocale("en");
  vi.clearAllTimers();
  vi.useRealTimers();
});
describe("annotation concurrency", () => {
  it("rejects discovery of a new session without rebinding old annotations", async () => {
    const s = initialized();
    s.meta!.session = "original";
    s.annotation!.notes = "unsaved original annotation";
    const original = JSON.stringify(s.annotation);
    mock.mockResolvedValue({
      ...metadata(),
      root: "/copy",
      session: "replacement",
    });
    await expect(s.refresh()).rejects.toThrow("Project changed");
    expect(s.meta!.session).toBe("original");
    expect(s.meta!.root).toBe("/tmp/p");
    expect(JSON.stringify(s.annotation)).toBe(original);
    expect(mock).toHaveBeenCalledTimes(1);
  });

  it("does not attach a late class response to a copied project with the same UUID", async () => {
    const s = initialized(),
      pending = deferred<any>();
    s.meta!.session = "A";
    mock.mockImplementation(async () => pending.promise);
    const add = s.addClass("Old project class");
    s.meta = { ...s.meta!, session: "B" };
    pending.resolve({
      id: "old-class",
      index: 1,
      name: "Old project class",
      color: "#123456",
    });
    await add;
    expect(s.meta!.classes).toHaveLength(1);
    expect(s.defaultClass).not.toBe("old-class");
  });
  it("does not silently adopt another runtime session during metadata refresh", async () => {
    const s = initialized();
    s.meta!.session = "A";
    mock.mockResolvedValue({
      ...metadata(),
      session: "B",
      root: "/another-copy",
    });
    await s.refreshMeta();
    expect(s.meta!.session).toBe("A");
    expect(s.meta!.root).toBe("/tmp/p");
  });
  it("marks project opening as navigation and prevents overlapping opens", async () => {
    const s = initialized(),
      pending = deferred<any>();
    mock.mockImplementation(async (path) => {
      if (path === "/project/open") return pending.promise;
      if (path === "/project") return { ...metadata("new"), session: "new" };
      return { items: [], total: 0 };
    });
    const opening = s.open("/new");
    for (let i = 0; i < 5; i++) await Promise.resolve();
    expect(s.navigating).toBe(true);
    await s.open("/overlapping");
    expect(
      mock.mock.calls.filter(([path]) => path === "/project/open"),
    ).toHaveLength(1);
    pending.resolve({});
    await opening;
    expect(s.navigating).toBe(false);
    expect(s.meta!.session).toBe("new");
  });
  it("ignores a metadata response from a project that is no longer open", async () => {
    const s = initialized(),
      pending = deferred<ProjectMeta>();
    mock.mockReturnValue(pending.promise);
    const refresh = s.refreshMeta();
    s.meta = metadata("other");
    pending.resolve(metadata());
    await refresh;
    expect(s.meta.id).toBe("other");
  });

  it.each(
    (["segment", "detect", "boxesFromMasks"] as const).flatMap((operation) =>
      (["en", "zh-CN"] as const).map(
        (language) => [operation, language] as const,
      ),
    ),
  )(
    "discards old %s responses after navigating away and back in %s",
    async (operation, language) => {
      setLocale(language);
      const s = initialized(),
        pending = deferred<Annotation>();
      const original = JSON.parse(JSON.stringify(s.annotation));
      mock.mockImplementation(async (path) =>
        path.endsWith("/annotation") ? original : pending.promise,
      );
      const run = s[operation]();
      for (let i = 0; i < 5; i++) await Promise.resolve();
      await s.load(s.images[1]);
      await s.load(s.images[0]);
      pending.resolve({ ...original, revision: 1, notes: "stale result" });
      await run;
      expect(s.current?.id).toBe("a");
      expect(s.annotation!.notes).toBe("");
    },
  );
  it("does not roll back an inference result when an older refresh returns late", async () => {
    const s = initialized(),
      pending = deferred<Annotation>();
    const original = JSON.parse(JSON.stringify(s.annotation));
    mock.mockImplementation(async (path) =>
      path.endsWith("/annotation")
        ? pending.promise
        : { ...original, revision: 1, notes: "inference saved" },
    );
    const refresh = s.refreshCurrent();
    await s.segment();
    pending.resolve(original);
    await refresh;
    expect(s.annotation!.revision).toBe(1);
    expect(s.annotation!.notes).toBe("inference saved");
  });
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
  it("marks a retained mask for review after a manual box edit and supports undo", () => {
    const s = initialized();
    const obj = s.annotation!.instances[0];
    obj.mask = { size: [10, 10], counts: "mask" };
    s.editBox(obj.id, [2, 2, 9, 9]);
    expect(obj.box).toEqual([2, 2, 9, 9]);
    expect(s.annotation!.detection_review).toBe("pending");
    expect(s.annotation!.segmentation_review).toBe("uncertain");
    expect(obj.mask).toEqual({ size: [10, 10], counts: "mask" });
    s.undo();
    expect(s.annotation!.instances[0].box).toEqual([1, 1, 8, 8]);
  });
  it("protects locked boxes and rejects degenerate coordinate edits", () => {
    const s = initialized();
    const obj = s.annotation!.instances[0];
    obj.locked = true;
    s.editBox(obj.id, [2, 2, 9, 9]);
    expect(obj.box).toEqual([1, 1, 8, 8]);
    obj.locked = false;
    s.editBox(obj.id, [9, 1, 8, 8]);
    s.editBox(obj.id, [NaN, 1, 8, 8]);
    expect(obj.box).toEqual([1, 1, 8, 8]);
    expect(s.dirty).toBe(false);
    s.editBox(obj.id, [-1, 1, 12, 8]);
    expect(obj.box).toEqual([0, 1, 10, 8]);
  });
  it("leaves segmentation review alone for box-only edits", () => {
    const s = initialized();
    s.editBox(s.annotation!.instances[0].id, [2, 2, 9, 9]);
    expect(s.annotation!.segmentation_review).toBe("ok");
  });
  it("can undo an ordinary segmentation result", async () => {
    const s = initialized();
    const original = JSON.parse(JSON.stringify(s.annotation));
    mock.mockResolvedValue({
      ...original,
      revision: 1,
      segmentation_review: "pending",
      instances: [
        {
          ...original.instances[0],
          mask: { size: [10, 10], counts: "new-mask" },
        },
      ],
    });
    await s.segment();
    expect(s.annotation!.instances[0].mask).not.toBeNull();
    s.undo();
    expect(s.annotation!.instances[0].mask).toBeNull();
    expect(s.annotation!.detection_review).toBe("ok");
    expect(s.annotation!.revision).toBe(1);
  });
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
  it("discards a late Apply after navigating away and back", async () => {
    const s = ready(),
      pending = deferred<Annotation>();
    const original = JSON.parse(JSON.stringify(s.annotation));
    mock.mockImplementation(async (path) => {
      if (path.endsWith("/mask-candidates")) return proposal(s);
      if (path.endsWith("/apply")) return pending.promise;
      return original;
    });
    await s.generateCandidates();
    const apply = s.applyCandidate();
    await flush();
    await s.load(s.images[1]);
    await s.load(s.images[0]);
    pending.resolve({
      ...original,
      revision: 1,
      notes: "stale candidate apply",
    });
    await apply;
    expect(s.current?.id).toBe("a");
    expect(s.annotation!.notes).toBe("");
    expect(s.history).toHaveLength(0);
  });
  it("clears a completed Apply session when a newer revision is already displayed", async () => {
    const s = ready(),
      pending = deferred<Annotation>();
    const original = JSON.parse(JSON.stringify(s.annotation));
    mock.mockImplementation(async (path) =>
      path.endsWith("/apply") ? pending.promise : proposal(s),
    );
    await s.generateCandidates();
    const apply = s.applyCandidate();
    await flush();
    s.annotation!.revision = 2;
    pending.resolve({ ...original, revision: 1 });
    await apply;
    expect(s.annotation!.revision).toBe(2);
    expect(s.candidates).toBeNull();
    expect(s.history).toHaveLength(0);
  });
});

describe("interactive single-mask prompts", () => {
  function prepare() {
    const s = initialized();
    const obj = s.annotation!.instances[0];
    obj.box = null;
    obj.prompt_box = [1, 1, 8, 8];
    s.selected = obj.id;
    return { s, obj };
  }
  function response(s: ReturnType<typeof useProject>) {
    return {
      project_id: s.meta!.id,
      image_id: s.current!.id,
      instance_id: s.selected,
      revision: s.annotation!.revision,
      image_stamp: "test",
      model: "sam",
      items: [
        {
          mask: { size: [10, 10], counts: "single" },
          polygons: [
            [
              [1, 1],
              [4, 1],
              [4, 4],
            ],
          ],
          quality: null,
          overlay: "",
        },
      ],
    };
  }
  function setupRequests(
    s: ReturnType<typeof useProject>,
    predict = () => Promise.resolve(response(s)),
  ) {
    mock.mockImplementation(async (path, method) => {
      if (path.endsWith("/mask-candidates")) return predict();
      if (method === "PUT")
        return { ...s.annotation, revision: s.annotation!.revision + 1 };
      return ann();
    });
  }
  async function flush() {
    for (let i = 0; i < 15; i++) await Promise.resolve();
  }
  it("coalesces clicks, requests single-mask inference and preserves instance/class/box", async () => {
    const { s, obj } = prepare();
    setupRequests(s);
    const id = obj.id,
      cls = obj.class_id;
    obj.points.push({ x: 2, y: 2, positive: true });
    s.changed("segmentation");
    s.promptsChanged();
    await vi.advanceTimersByTimeAsync(200);
    obj.points.push({ x: 7, y: 7, positive: false });
    s.changed("segmentation");
    s.promptsChanged();
    await vi.advanceTimersByTimeAsync(350);
    await flush();
    const calls = mock.mock.calls.filter(([path]) =>
      path.endsWith("/mask-candidates"),
    );
    expect(calls).toHaveLength(1);
    expect(calls[0][2]).toMatchObject({
      multimask_output: false,
      instance_id: id,
    });
    expect(s.object).toMatchObject({
      id,
      class_id: cls,
      box: null,
      source: "sam",
    });
    expect(s.object!.mask).toBeTruthy();
    expect(s.annotation!.segmentation_review).toBe("pending");
    expect(s.promptStatus).toBe("Mask updated");
  });
  it("discards an in-flight result after newer prompts and runs only the latest", async () => {
    const { s, obj } = prepare();
    const pending = deferred<any>();
    let count = 0;
    setupRequests(s, () =>
      ++count === 1 ? pending.promise : Promise.resolve(response(s)),
    );
    s.changed("segmentation");
    s.promptsChanged();
    await vi.advanceTimersByTimeAsync(350);
    const old = response(s);
    obj.points.push({ x: 3, y: 3, positive: true });
    s.changed("segmentation");
    s.promptsChanged();
    await vi.advanceTimersByTimeAsync(350);
    expect(count).toBe(1);
    pending.resolve({
      ...old,
      items: [{ ...old.items[0], mask: { counts: "stale" } }],
    });
    await flush();
    expect(count).toBe(2);
    expect(s.object!.mask).toMatchObject({ counts: "single" });
  });
  it.each(["navigation", "edit", "model", "tool", "new object"])(
    "discards obsolete auto masks after %s",
    async (change) => {
      const { s } = prepare();
      const pending = deferred<any>();
      setupRequests(s, () => pending.promise);
      s.changed("segmentation");
      s.promptsChanged();
      await vi.advanceTimersByTimeAsync(350);
      const old = response(s);
      if (change === "navigation") await s.load(s.images[1]);
      else if (change === "edit") {
        s.annotation!.notes = "new";
        s.changed();
      } else if (change === "model") s.model = "other";
      else if (change === "new object") s.newObject();
      else s.tool = "select-other";
      pending.resolve(old);
      await flush();
      expect(s.annotation!.instances[0].mask).toBeNull();
      expect(s.promptStatus).not.toBe("Updating mask…");
    },
  );
  it("clearing all prompts cancels late masks and never restores a removed prompt-only draft", async () => {
    const { s } = prepare();
    const pending = deferred<any>();
    setupRequests(s, () => pending.promise);
    s.changed("segmentation");
    s.promptsChanged();
    await vi.advanceTimersByTimeAsync(350);
    const old = response(s);
    s.clearAllPrompts();
    pending.resolve(old);
    await flush();
    expect(s.annotation!.instances).toHaveLength(0);
    expect(s.candidates).toBeNull();
  });
  it("shares one in-flight request with candidate mode and discards its old single mask", async () => {
    const { s } = prepare();
    const pending = deferred<any>();
    let count = 0;
    s.model = "sam";
    s.models = {
      config: "models.json",
      default_model: "sam",
      models: [
        {
          id: "sam",
          name: "SAM",
          backend: "sam2",
          task: "segmentation",
          available: true,
          mask_candidates: true,
          text_prompts: false,
          path: null,
          error: null,
        },
      ],
    };
    setupRequests(s, () =>
      ++count === 1 ? pending.promise : Promise.resolve(response(s)),
    );
    s.changed("segmentation");
    s.promptsChanged();
    await vi.advanceTimersByTimeAsync(350);
    const old = response(s);
    await s.generateCandidates();
    expect(count).toBe(1);
    pending.resolve(old);
    await flush();
    expect(count).toBe(2);
    expect(s.candidates?.phase).toBe("ready");
    expect(s.object!.mask).toBeNull();
    const calls = mock.mock.calls.filter(([path]) =>
      path.endsWith("/mask-candidates"),
    );
    expect(calls[0][2]).toMatchObject({ multimask_output: false });
    expect(calls[1][2]).not.toHaveProperty("multimask_output");
  });
  it("deletes a selected point or prompt box without deleting the mask or instance, and supports undo", async () => {
    const { s, obj } = prepare();
    obj.mask = { counts: "original" };
    obj.points = [{ x: 2, y: 2, positive: true }];
    s.selectedPrompt = 0;
    s.deleteSelected();
    expect(s.object!.points).toHaveLength(0);
    expect(s.object!.mask).toMatchObject({ counts: "original" });
    s.undo();
    expect(s.annotation!.instances[0].points).toHaveLength(1);
    s.selectPrompt(obj.id, "box");
    s.deleteSelected();
    expect(s.object!.prompt_box).toBeNull();
    expect(s.annotation!.instances).toHaveLength(1);
    s.deletePrompt(true);
    await vi.advanceTimersByTimeAsync(400);
    expect(
      mock.mock.calls.filter(([path]) => path.endsWith("/mask-candidates")),
    ).toHaveLength(0);
    expect(s.object!.mask).toMatchObject({ counts: "original" });
  });
  it("keeps the current mask after a failed prediction", async () => {
    const { s, obj } = prepare();
    obj.mask = { counts: "original" };
    setupRequests(s, () => Promise.reject(new Error("Model unavailable")));
    s.changed("segmentation");
    s.promptsChanged();
    await vi.advanceTimersByTimeAsync(350);
    expect(s.object!.mask).toMatchObject({ counts: "original" });
    expect(s.error).toContain("Model unavailable");
    expect(s.promptStatus).toContain("failed");
  });
  it("does not report missing selection when Segment current has no work", async () => {
    const { s, obj } = prepare();
    obj.mask = { counts: "existing" };
    await s.segment(true);
    await s.segment(true);
    expect(mock).not.toHaveBeenCalled();
    expect(s.error).toBe("");
    expect(s.promptStatus).toContain("No missing masks");
  });
});

describe("independent geometry deletion", () => {
  it.each(["box", "mask"] as const)(
    "deleting selected %s preserves the other geometry and supports undo",
    (geometry) => {
      const s = initialized();
      const obj = s.annotation!.instances[0];
      const box = [...obj.box!];
      obj.mask = { size: [10, 10], counts: "original" };
      obj.polygons = [
        [
          [1, 1],
          [8, 1],
          [8, 8],
        ],
      ];
      s.selected = obj.id;
      s.selectedGeometry = geometry;
      s.deleteSelected();
      expect(s.annotation!.instances).toHaveLength(1);
      if (geometry === "box") {
        expect(obj.box).toBeNull();
        expect(obj.mask).toBeTruthy();
        expect(s.annotation!.segmentation_review).toBe("ok");
      } else {
        expect(obj.box).toEqual(box);
        expect(obj.mask).toBeNull();
        expect(obj.polygons).toEqual([]);
        expect(s.annotation!.detection_review).toBe("ok");
      }
      s.undo();
      expect(s.annotation!.instances[0].box).toEqual(box);
      expect(s.annotation!.instances[0].mask).toBeTruthy();
    },
  );
});

describe("continuous object annotation", () => {
  it("starts the next object without mutating or creating an empty annotation", () => {
    const s = initialized();
    const obj = s.annotation!.instances[0];
    obj.mask = { counts: "existing" };
    obj.points = [{ x: 2, y: 2, positive: true }];
    s.selected = obj.id;
    s.tool = "negative";
    const before = JSON.stringify(s.annotation);
    s.newObject();
    expect(s.selected).toBeNull();
    expect(s.tool).toBe("positive");
    expect(JSON.stringify(s.annotation)).toBe(before);
    expect(s.promptStatus).toContain("new object");
    s.tool = "promptbox";
    s.newObject();
    expect(s.tool).toBe("promptbox");
    s.task = "detection";
    s.newObject();
    expect(s.tool).toBe("box");
  });
  it("deleting the whole object removes its prompts while preserving other objects and can be undone", () => {
    const s = initialized();
    const obj = s.annotation!.instances[0];
    obj.mask = { counts: "old" };
    obj.points = [
      { x: 2, y: 2, positive: true },
      { x: 8, y: 8, positive: false },
    ];
    obj.prompt_box = [1, 1, 8, 8];
    const other = instance("c");
    s.annotation!.instances.push(other);
    s.selected = obj.id;
    s.selectedGeometry = "mask";
    s.remove();
    expect(s.annotation!.instances.map((o) => o.id)).toEqual([other.id]);
    s.undo();
    expect(s.annotation!.instances[0]).toMatchObject({
      id: obj.id,
      mask: { counts: "old" },
      points: obj.points,
      prompt_box: obj.prompt_box,
    });
  });
});

it("Clear prompts preserves an accepted mask even when the detection box remains", async () => {
  const s = initialized();
  const obj = s.annotation!.instances[0];
  s.selected = obj.id;
  obj.mask = { counts: "accepted" };
  obj.points = [{ x: 3, y: 3, positive: true }];
  obj.prompt_box = [2, 2, 7, 7];
  const box = [...obj.box!];
  mock.mockImplementation(async () => ({ ...s.annotation, revision: 1 }));
  s.deletePrompt(true);
  await vi.advanceTimersByTimeAsync(600);
  expect(obj.mask).toEqual({ counts: "accepted" });
  expect(obj.box).toEqual(box);
  expect(obj.points).toEqual([]);
  expect(obj.prompt_box).toBeNull();
  expect(
    mock.mock.calls.some(([path]) => path.endsWith("/mask-candidates")),
  ).toBe(false);
});

it("switches explicit geometry targets without changing annotation data", () => {
  const s = initialized();
  const obj = s.annotation!.instances[0];
  obj.mask = { counts: "mask" };
  obj.prompt_box = [1, 1, 8, 8];
  obj.points = [{ x: 2, y: 2, positive: true }];
  const before = JSON.stringify(s.annotation);
  s.tool = "positive";
  s.selectPrompt(obj.id, "box");
  expect(s.tool).toBe("select");
  expect(s.selectionTarget).toBe("prompts");
  expect(s.selectedPrompt).toBe("box");
  s.selectGeometry(obj.id, "box");
  expect(s.selectionTarget).toBe("results");
  expect(s.selectedGeometry).toBe("box");
  expect(s.selectedPrompt).toBeNull();
  s.selectGeometry(obj.id, "mask");
  expect(s.selectedGeometry).toBe("mask");
  s.selectPrompt(obj.id, 0);
  expect(s.selectionTarget).toBe("prompts");
  expect(s.selectedPrompt).toBe(0);
  expect(s.selectedGeometry).toBeNull();
  expect(JSON.stringify(s.annotation)).toBe(before);
});

describe("image-wide prompt clearing", () => {
  it("clears all unlocked prompts in one undo step, retaining masks, boxes and locked objects", () => {
    const s = initialized();
    const first = s.annotation!.instances[0];
    first.mask = { counts: "one" };
    first.points = [{ x: 2, y: 2, positive: true }];
    first.prompt_box = [1, 1, 8, 8];
    const second = instance("c");
    second.mask = { counts: "two" };
    second.points = [{ x: 5, y: 5, positive: false }];
    second.hidden = true;
    const locked = instance("c");
    locked.locked = true;
    locked.points = [{ x: 4, y: 4, positive: true }];
    locked.prompt_box = [2, 2, 7, 7];
    const draft = instance("c");
    draft.points = [{ x: 3, y: 3, positive: true }];
    s.annotation!.instances.push(second, locked, draft);
    s.selected = first.id;
    s.selectedPrompt = 0;
    const before = JSON.stringify(s.annotation);
    expect(s.canClearAllPrompts).toBe(true);
    s.clearAllPrompts();
    expect(first.points).toEqual([]);
    expect(first.prompt_box).toBeNull();
    expect(first.mask).toEqual({ counts: "one" });
    expect(first.box).toEqual([1, 1, 8, 8]);
    expect(second.points).toEqual([]);
    expect(second.mask).toEqual({ counts: "two" });
    expect(locked.points).toHaveLength(1);
    expect(locked.prompt_box).toEqual([2, 2, 7, 7]);
    expect(s.annotation!.instances.map((o) => o.id)).not.toContain(draft.id);
    expect(s.selectedPrompt).toBeNull();
    expect(s.canClearAllPrompts).toBe(false);
    expect(s.history).toHaveLength(1);
    s.undo();
    expect(JSON.stringify({ ...s.annotation, segmentation_review: "ok" })).toBe(
      before,
    );
  });
  it("does nothing when all remaining prompts are locked", () => {
    const s = initialized();
    s.annotation!.instances[0].locked = true;
    s.annotation!.instances[0].points = [{ x: 2, y: 2, positive: true }];
    const before = JSON.stringify(s.annotation);
    s.clearAllPrompts();
    expect(JSON.stringify(s.annotation)).toBe(before);
    expect(s.history).toHaveLength(0);
  });
});

it("shares explicit box padding parameters between current-image and batch payloads", () => {
  const s = useProject();
  s.boxPadding = {
    box_padding_mode: "ratio",
    box_padding_pixels: 8,
    box_padding_ratio: 0.1,
    box_padding_min: true,
  };
  expect(s.parameters("boxes_from_masks")).toMatchObject(s.boxPadding);
  expect(s.parameters("segmentation")).not.toHaveProperty("box_padding_pixels");
  expect(s.parameters("detection")).not.toHaveProperty("box_padding_pixels");
});

it("ordinary selection restores result targeting without touching annotation data", () => {
  const s = initialized();
  const obj = s.annotation!.instances[0];
  obj.points = [{ x: 2, y: 2, positive: true }];
  s.selectPrompt(obj.id, 0);
  const before = JSON.stringify(s.annotation);
  s.activateSelection();
  expect(s.tool).toBe("select");
  expect(s.selectionTarget).toBe("results");
  expect(s.selectedPrompt).toBeNull();
  expect(JSON.stringify(s.annotation)).toBe(before);
});
it("clears all unlocked image annotations in one undo step and preserves image metadata", () => {
  const s = initialized();
  const unlocked = s.annotation!.instances[0];
  unlocked.mask = { counts: "mask" };
  unlocked.points = [{ x: 2, y: 2, positive: true }];
  const locked = instance("c");
  locked.locked = true;
  locked.prompt_box = [1, 1, 3, 3];
  s.annotation!.instances.push(locked);
  s.annotation!.tags = ["custom"];
  s.annotation!.notes = "keep";
  s.annotation!.explicit_empty = { detection: true, segmentation: true };
  const objects = JSON.stringify(s.annotation!.instances);
  s.selected = unlocked.id;
  s.selectedGeometry = "mask";
  s.clearImageAnnotations();
  expect(s.annotation!.instances.map((o) => o.id)).toEqual([locked.id]);
  expect(s.annotation).toMatchObject({
    notes: "keep",
    tags: ["custom"],
    detection_review: "pending",
    segmentation_review: "pending",
    explicit_empty: { detection: false, segmentation: false },
  });
  expect(s.selected).toBeNull();
  expect(s.selectedGeometry).toBeNull();
  expect(s.history).toHaveLength(1);
  s.undo();
  expect(JSON.stringify(s.annotation!.instances)).toBe(objects);
  expect(s.annotation!.explicit_empty).toEqual({
    detection: true,
    segmentation: true,
  });
});
it("requires explicit inclusion to remove locked objects and ignores clearing during navigation", () => {
  const s = initialized();
  s.annotation!.instances[0].locked = true;
  s.clearImageAnnotations();
  expect(s.history).toHaveLength(0);
  s.navigating = true;
  s.clearImageAnnotations(true);
  expect(s.annotation!.instances).toHaveLength(1);
  s.navigating = false;
  s.clearImageAnnotations(true);
  expect(s.annotation!.instances).toHaveLength(0);
  expect(s.history).toHaveLength(1);
  s.undo();
  expect(s.annotation!.instances[0].locked).toBe(true);
});
it("discards a late model result after image annotations are cleared", async () => {
  const s = initialized(),
    pending = deferred<Annotation>();
  const old = JSON.parse(JSON.stringify(s.annotation));
  mock.mockImplementation(async (path) =>
    path.endsWith("/segment") ? pending.promise : s.annotation!,
  );
  const run = s.segment();
  await Promise.resolve();
  await Promise.resolve();
  s.clearImageAnnotations(true);
  pending.resolve({ ...old, revision: 1 });
  await run;
  expect(s.annotation!.instances).toHaveLength(0);
});

it("enables auto segmentation by default and fills only pending visible unlocked boxes", async () => {
  const s = initialized();
  expect(s.autoSegment).toBe(true);
  s.model = "sam";
  s.models = {
    config: "test",
    default_model: "sam",
    models: [
      {
        id: "sam",
        name: "SAM",
        backend: "sam2",
        available: true,
        path: "/tmp/model",
        error: null,
        text_prompts: false,
      },
    ],
  };
  const target = ann();
  target.segmentation_review = "pending";
  mock.mockImplementation(async (path) =>
    path.endsWith("/segment") ? { ...target, revision: 1 } : target,
  );
  await s.load(s.images[1]);
  for (let i = 0; i < 10; i++) await Promise.resolve();
  expect(mock.mock.calls.some(([path]) => path.endsWith("/segment"))).toBe(
    true,
  );
});
it.each(["excluded", "reviewed", "locked", "hidden", "missing-model"])(
  "does not auto-segment %s images/objects",
  async (reason) => {
    const s = initialized();
    s.model = "sam";
    s.models = {
      config: "test",
      default_model: "sam",
      models: [
        {
          id: "sam",
          name: "SAM",
          backend: "sam2",
          available: reason !== "missing-model",
          path: null,
          error: null,
          text_prompts: false,
        },
      ],
    };
    const target = ann();
    target.segmentation_review = reason === "reviewed" ? "ok" : "pending";
    target.excluded = reason === "excluded";
    target.instances[0].locked = reason === "locked";
    target.instances[0].hidden = reason === "hidden";
    mock.mockResolvedValue(target);
    await s.load(s.images[1]);
    for (let i = 0; i < 10; i++) await Promise.resolve();
    expect(mock.mock.calls.some(([path]) => path.endsWith("/segment"))).toBe(
      false,
    );
  },
);

it("requires explicit empty confirmation for approval but permits needs-review and exclusion", () => {
  const s = initialized();
  s.annotation!.instances = [];
  s.annotation!.segmentation_review = "pending";
  s.setReview("ok");
  expect(s.annotation!.segmentation_review).toBe("pending");
  expect(s.error).toContain("explicitly confirm");
  s.setReview("uncertain");
  expect(s.annotation!.segmentation_review).toBe("uncertain");
  s.setReview("excluded");
  expect(s.annotation!.excluded).toBe(true);
  s.setReview("excluded");
  s.setExplicitEmpty(true);
  s.setReview("ok");
  expect(s.annotation!.segmentation_review).toBe("ok");
  s.setExplicitEmpty(false);
  expect(s.annotation!.segmentation_review).toBe("pending");
});
