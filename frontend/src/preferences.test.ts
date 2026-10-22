import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createSSRApp } from "vue";
import { createPinia } from "pinia";
import { renderToString } from "@vue/server-renderer";
import App from "./App.vue";
import { configureApi, apiBase } from "./api";
import { setLocale } from "./i18n";
import { readPreference, writePreference } from "./preferences";

function blockStorage(getter: boolean) {
  vi.stubGlobal("localStorage", undefined);
  const denied = () => {
    throw new DOMException("Storage denied", "SecurityError");
  };
  if (getter)
    Object.defineProperty(globalThis, "localStorage", {
      configurable: true,
      get: denied,
    });
  else vi.stubGlobal("localStorage", { getItem: denied, setItem: denied });
}
beforeEach(() => {
  vi.stubGlobal("document", {
    documentElement: { lang: "en" },
    addEventListener() {},
    removeEventListener() {},
    hidden: false,
  });
});
afterEach(() => {
  setLocale("en");
  vi.unstubAllGlobals();
});

describe("optional browser persistence", () => {
  it("reads and writes existing preference keys when storage works", () => {
    const values = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
    });
    writePreference("lb-left", "330");
    expect(readPreference("lb-left")).toBe("330");
    expect(readPreference("missing")).toBeNull();
  });
  it("tolerates absent storage and write quota failures", () => {
    vi.stubGlobal("localStorage", undefined);
    expect(readPreference("lb-left")).toBeNull();
    expect(() => writePreference("lb-left", "330")).not.toThrow();
    vi.stubGlobal("localStorage", {
      getItem: () => null,
      setItem: () => {
        throw new DOMException("Full", "QuotaExceededError");
      },
    });
    expect(() => writePreference("lb-left", "330")).not.toThrow();
  });
  it.each([true, false])(
    "renders the real workbench and configures the API with blocked storage (getter=%s)",
    async (getter) => {
      blockStorage(getter);
      expect(readPreference("annodesk-api")).toBeNull();
      expect(() => writePreference("lb-left", "330")).not.toThrow();
      const fetch = vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ apiBase: "/remote/api/v1" })),
        );
      vi.stubGlobal("fetch", fetch);
      await configureApi();
      expect(apiBase).toBe("/remote/api/v1");
      // The actual App setup/template must render, including the default layout.
      for (const language of ["en", "zh-CN"]) {
        setLocale(language);
        const app = createSSRApp(App);
        app.use(createPinia());
        const html = await renderToString(app);
        expect(html).toContain("AnnoDesk");
        expect(html).toContain('class="workspace"');
        expect(html).toContain("--left:260px");
        expect(html).toContain("--right:290px");
        expect(html).toContain("height:53%");
        expect(html).toContain(language === "en" ? "Images" : "图片");
      }
    },
  );
  it("retains saved layout and API overrides when storage is available", async () => {
    const values: Record<string, string> = {
      "lb-left": "330",
      "lb-right": "320",
      "lb-top": "60",
      "annodesk-api": "/preferred/api/v1",
    };
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => values[key] ?? null,
      setItem() {},
    });
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(
          new Response(JSON.stringify({ apiBase: "/api/v1" })),
        ),
    );
    await configureApi();
    expect(apiBase).toBe("/preferred/api/v1");
    const app = createSSRApp(App);
    app.use(createPinia());
    const html = await renderToString(app);
    expect(html).toContain("--left:330px");
    expect(html).toContain("--right:320px");
    expect(html).toContain("height:60%");
  });
});
