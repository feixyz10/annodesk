import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { createRenderer, h, nextTick, reactive, ssrContextKey } from "vue";
import { createPinia, setActivePinia } from "pinia";
import { request } from "./api";
import { useProject } from "./stores/project";
import App from "./App.vue";
import ExportSetup from "./components/ExportSetup.vue";
import BatchSetup from "./components/BatchSetup.vue";
import StatisticsBar from "./components/StatisticsBar.vue";
vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  request: vi.fn(),
  configureApi: vi.fn(),
}));
const mock = vi.mocked(request);
let dispose: () => void;
beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("document", {
    hidden: false,
    addEventListener() {},
    removeEventListener() {},
  });
  vi.stubGlobal("window", { addEventListener() {}, removeEventListener() {} });
  mock.mockReset();
});
afterEach(() => {
  dispose?.();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});
async function setup(component: any, input: Record<string, unknown> = {}) {
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
  store.model = "sam";
  store.detectionModel = "yolo";
  vi.spyOn(store, "save").mockResolvedValue();
  vi.spyOn(store, "refreshModels").mockResolvedValue();
  vi.spyOn(store, "refresh").mockResolvedValue();
  vi.spyOn(store, "refreshCurrent").mockResolvedValue();
  vi.spyOn(store, "refreshMeta").mockImplementation(async () => {
    store.meta = { ...store.meta! };
  });
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
  const props = reactive(input);
  let vm: any;
  const mounted = { ...component, render: () => h("div") };
  const app = renderer.createApp({
    render: () =>
      h(mounted, {
        ...props,
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
  return { store, props, state: vm.$.setupState };
}
async function flush() {
  for (let i = 0; i < 12; i++) {
    await Promise.resolve();
    await nextTick();
  }
}
const finished = {
  id: "job",
  kind: "segmentation",
  status: "completed",
  failed: [],
};
it("keeps completed tasks stable across metadata refreshes and restart polling", async () => {
  mock.mockResolvedValue([finished]);
  const { state, store } = await setup(App);
  await state.refreshJobs();
  await flush();
  expect(state.jobs).toHaveLength(1);
  expect(store.refreshCurrent).toHaveBeenCalledTimes(1);
  expect(mock).toHaveBeenCalledTimes(1);
  await vi.advanceTimersByTimeAsync(4000);
  expect(mock).toHaveBeenCalledTimes(5);
  expect(state.jobs).toHaveLength(1);
  expect(store.refreshCurrent).toHaveBeenCalledTimes(1);
});
it("refreshes annotations once when a running task completes", async () => {
  mock.mockResolvedValue([{ ...finished, status: "running" }]);
  const { state, store } = await setup(App);
  await state.refreshJobs();
  mock.mockResolvedValue([finished]);
  await state.refreshJobs();
  await flush();
  await state.refreshJobs();
  await flush();
  expect(store.refreshCurrent).toHaveBeenCalledTimes(1);
});
it("does not clear or reload statistics for same-session metadata updates", async () => {
  const stats = { status: "ready", total: 1 };
  mock.mockResolvedValue(stats);
  const { state, store } = await setup(StatisticsBar, { active: false });
  await flush();
  expect(state.stats).toEqual(stats);
  store.meta = { ...store.meta! };
  await flush();
  expect(state.stats).toEqual(stats);
  expect(mock).toHaveBeenCalledTimes(1);
  store.meta = { ...store.meta!, session: "new" };
  await flush();
  expect(mock).toHaveBeenCalledTimes(2);
});
it("starts without a manual preview, after save and fresh preflight", async () => {
  mock.mockResolvedValue({ total: 2 });
  const started = vi.fn();
  const { state, store } = await setup(BatchSetup, {
    show: true,
    onStarted: started,
  });
  expect(state.preview).toBeNull();
  await state.start();
  expect(store.save).toHaveBeenCalledTimes(1);
  expect(mock.mock.calls.map((c) => c[0])).toEqual(["/jobs/preview", "/jobs"]);
  expect(started).toHaveBeenCalledTimes(1);
});
it("shows an empty scope without launching a job", async () => {
  mock.mockResolvedValue({ total: 0 });
  const { state } = await setup(BatchSetup, { show: true });
  await state.start();
  expect(state.preview.total).toBe(0);
  expect(mock.mock.calls.map((c) => c[0])).toEqual(["/jobs/preview"]);
});
it.each(["close", "session", "settings"])(
  "does not start after %s during preflight",
  async (change) => {
    let resolve!: (v: any) => void;
    mock.mockImplementation(
      () =>
        new Promise((r) => {
          resolve = r;
        }),
    );
    const { state, store, props } = await setup(BatchSetup, { show: true });
    const flight = state.start();
    await flush();
    if (change === "close") props.show = false;
    if (change === "session") store.meta = { ...store.meta!, session: "other" };
    if (change === "settings") state.workers = "2";
    await nextTick();
    resolve({ total: 2 });
    await flight;
    expect(mock.mock.calls.map((c) => c[0])).toEqual(["/jobs/preview"]);
  },
);
it("checks detector compatibility before starting and permits retry on errors", async () => {
  mock.mockImplementation(async (url) => {
    if (url === "/jobs/preview") return { total: 1 };
    if (url === "/models/check") throw new Error("Incompatible classes");
  });
  const { state } = await setup(BatchSetup, { show: true });
  state.operation = "detection";
  await nextTick();
  await state.start();
  expect(state.error).toContain("Incompatible");
  expect(state.busy).toBe("");
  expect(mock.mock.calls.map((c) => c[0])).toEqual([
    "/jobs/preview",
    "/models/check",
  ]);
  mock.mockResolvedValue({ total: 1, compatibility: { accepted_classes: 1 } });
  await state.start();
  expect(mock.mock.calls.at(-1)?.[0]).toBe("/jobs");
});

const exportPlan = {
  skipped_by_state: {},
  skipped_no_valid_annotations: {},
  no_valid_annotations: {},
  skipped_images: [],
  total: 1,
  counts: { pending: 1 },
  eligible: 1,
  skipped: {},
  errors: [],
  signature: "sig",
  output: "/tmp/out",
  already_exported: false,
};
it("shows export statistics without starting until explicit confirmation", async () => {
  mock.mockResolvedValue(exportPlan);
  const { state } = await setup(ExportSetup, { show: true });
  await flush();
  expect(mock.mock.calls.map((c) => c[0])).toEqual(["/export/preview"]);
  expect(state.preview.eligible).toBe(1);
  await state.start();
  expect(mock.mock.calls.at(-1)).toEqual([
    "/export/jobs",
    "POST",
    {
      task: "segmentation",
      format: "yolo",
      include_pending: false,
      output: "/tmp/out",
      expected_signature: "sig",
    },
  ]);
});
it("invalidates export confirmation on destination or scope changes", async () => {
  mock.mockResolvedValue(exportPlan);
  const { state } = await setup(ExportSetup, { show: true });
  await flush();
  state.includePending = true;
  state.output = "/tmp/custom";
  await vi.advanceTimersByTimeAsync(350);
  await flush();
  expect(mock.mock.calls.at(-1)).toEqual([
    "/export/preview",
    "POST",
    {
      task: "segmentation",
      format: "yolo",
      include_pending: true,
      output: "/tmp/custom",
    },
  ]);
});
it.each([
  { ...exportPlan, eligible: 0 },
  { ...exportPlan, already_exported: true },
  { ...exportPlan, errors: [{ image: "bad", error: "bad" }] },
])("does not export empty, duplicate or invalid summaries", async (plan) => {
  mock.mockResolvedValue(plan);
  const { state } = await setup(ExportSetup, { show: true });
  await flush();
  await state.start();
  expect(mock.mock.calls.map((c) => c[0])).toEqual(["/export/preview"]);
});
it("discards a late export preview after closing", async () => {
  let resolve!: (v: any) => void;
  mock.mockImplementation(
    () =>
      new Promise((r) => {
        resolve = r;
      }),
  );
  const { state, props } = await setup(ExportSetup, { show: true });
  await flush();
  props.show = false;
  await nextTick();
  resolve(exportPlan);
  await flush();
  expect(state.preview).toBeNull();
});
it("keeps automatic detection disabled by default", async () => {
  const { store } = await setup(BatchSetup, { show: false });
  expect(store.autoDetect).toBe(false);
});
