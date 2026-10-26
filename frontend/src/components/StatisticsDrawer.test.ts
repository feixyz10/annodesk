import { afterEach, expect, it, vi } from "vitest";
import { createSSRApp } from "vue";
import { createPinia, setActivePinia } from "pinia";
import { renderToString } from "@vue/server-renderer";
import { setLocale } from "../i18n";
import { type ProjectStatistics } from "../api";
import StatisticsDrawer from "./StatisticsDrawer.vue";
vi.mock("naive-ui", async () => {
  const { h } = await import("vue");
  const wrapper = {
    setup(_: unknown, { slots }: { slots: any }) {
      return () => h("section", slots.default?.());
    },
  };
  return { NModal: wrapper };
});
afterEach(() => setLocale("en"));
it.each(["en", "zh-CN"])(
  "renders per-class table, scope and partial-count warning (%s)",
  async (language) => {
    setLocale(language);
    const pinia = createPinia();
    setActivePinia(pinia);
    const stats: ProjectStatistics = {
      total: 3,
      counts: { pending: 3 },
      reviewed: 0,
      statistics_revision: 1,
      status: "ready",
      boxes: 8,
      masks: 5,
      instances: 10,
      include_excluded: false,
      invalid_images: 1,
      classes: [
        {
          class_id: "c",
          index: 7,
          name: "长类别名称 / person",
          color: "#24835d",
          boxes: 8,
          masks: 5,
          instances: 10,
          images: 2,
        },
      ],
    };
    const app = createSSRApp(StatisticsDrawer, {
      show: true,
      stats,
      includeExcluded: false,
      error: "",
    });
    app.use(pinia);
    const html = await renderToString(app);
    expect(html).toContain("长类别名称 / person");
    expect(html).toContain("8");
    expect(html).toContain("5");
    for (const text of language === "en"
      ? [
          "Include excluded images",
          "Bar chart",
          "Table",
          "1 images with unreadable annotations",
        ]
      : ["包含已排除图片", "柱状图", "表格", "1 张标注无法读取的图片"])
      expect(html).toContain(text);
    expect(html).toContain('scope="row"');
    expect(html).toContain('aria-pressed="true"');
  },
);
