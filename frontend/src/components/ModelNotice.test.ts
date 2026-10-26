import { afterEach, describe, expect, it } from "vitest";
import { createSSRApp } from "vue";
import { renderToString } from "@vue/server-renderer";
import type { ModelsConfig } from "../api";
import { setLocale } from "../i18n";
import ModelNotice from "./ModelNotice.vue";
const sam = "facebook/sam2.1-hiera-tiny";
function config(available = false, dependencies: string[] = []): ModelsConfig {
  return {
    config: "/private/config/models.json",
    default_model: sam,
    default_detection_model: "yolo11n",
    missing_dependencies: dependencies,
    models: [
      {
        id: sam,
        name: "SAM 2.1 Tiny",
        backend: "sam2",
        task: "segmentation",
        available,
        path: null,
        error: "Checked secret server path /private/weights",
        text_prompts: false,
      },
      {
        id: "yolo11n",
        name: "YOLO11n",
        backend: "ultralytics",
        task: "detection",
        available: true,
        path: "/private/weights",
        error: null,
        text_prompts: false,
      },
    ],
  };
}
async function render(
  value: ModelsConfig | null,
  task: "detection" | "segmentation" = "segmentation",
  modelId = sam,
) {
  return renderToString(
    createSSRApp(ModelNotice, {
      config: value,
      task,
      modelId,
      settingsButton: true,
    }),
  );
}
afterEach(() => setLocale("en"));
describe("model preparation notice", () => {
  it.each(["en", "zh-CN"])(
    "shows missing SAM despite bundled YOLO, without exposing paths (%s)",
    async (language) => {
      setLocale(language);
      const html = await render(config());
      expect(html).toContain(sam);
      expect(html).not.toContain("HF_MODELS");
      expect(html).toContain(
        language === "en" ? "was not found locally" : "找不到模型",
      );
      expect(html).toContain(
        language === "en"
          ? "Manual annotation remains available"
          : "仍可手工标注",
      );
      expect(html).toContain(
        language === "en" ? "Open Models" : "打开模型设置",
      );
      expect(html).not.toContain("/private");
      expect(html).not.toContain("Checked secret");
    },
  );
  it("keeps dependency failures separate from available weights", async () => {
    const html = await render(config(true, ["torch", "ultralytics"]));
    expect(html).toContain("torch, ultralytics");
    expect(html).toContain("annodesk[inference]");
    expect(html).not.toContain("is unavailable");
  });
  it("stays hidden while loading and when the selected task is ready", async () => {
    expect(await render(null)).not.toContain('role="status"');
    expect(await render(config(), "detection", "yolo11n")).not.toContain(
      'role="status"',
    );
    expect(await render(config(true))).not.toContain('role="status"');
  });
  it("explains an absent task instead of offering an incorrect model", async () => {
    const html = await render(config(), "detection", "unknown");
    expect(html).toContain("No Detection model is configured");
    expect(html).toContain("models.json");
  });
});
