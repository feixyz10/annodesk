import { afterEach, expect, it, vi } from "vitest";
import { createSSRApp } from "vue";
import { createPinia, setActivePinia } from "pinia";
import { renderToString } from "@vue/server-renderer";
import { instance } from "../api";
import { setLocale } from "../i18n";
import { useProject } from "../stores/project";
import SelectedObjectActions from "./SelectedObjectActions.vue";
vi.mock("naive-ui", () => ({
  NSelect: {
    props: ["value", "options"],
    template: "<select />",
    ssrRender(_: unknown, push: (s: string) => void) {
      push('<select aria-label="Change class"></select>');
    },
  },
}));
afterEach(() => setLocale("en"));
it.each(["en", "zh-CN"])(
  "exposes selected object commands and precise deletion targets (%s)",
  async (language) => {
    setLocale(language);
    const pinia = createPinia();
    setActivePinia(pinia);
    const s = useProject(pinia);
    const obj = instance(null, [1, 1, 8, 8]);
    obj.mask = { counts: "test" };
    obj.prompt_box = [1, 1, 8, 8];
    obj.points = [{ x: 2, y: 2, positive: true }];
    s.annotation = {
      revision: 0,
      instances: [obj],
      detection_review: "pending",
      segmentation_review: "pending",
      excluded: false,
      tags: [],
      notes: "",
      explicit_empty: {},
      width: 10,
      height: 10,
    };
    s.selected = obj.id;
    const app = createSSRApp(SelectedObjectActions);
    app.use(pinia);
    const render = () => renderToString(app);
    for (const geometry of ["box", "mask"] as const) {
      s.selectedGeometry = geometry;
      const html = await render();
      expect(html).toContain(language === "en" ? "Refine mask" : "细化掩膜");
      expect(html).toContain(language === "en" ? "Detection box" : "检测框");
      expect(html).toContain(
        language === "en" ? "SAM box prompt" : "SAM提示框",
      );
      expect(html).toContain(language === "en" ? "Prompt details" : "提示详情");
      expect(html).toContain(language === "en" ? "Clear prompts" : "清空提示");
      expect(html).toContain(language === "en" ? "Delete object" : "删除实例");
      expect(html).toContain(
        language === "en" ? "Generate candidates" : "生成候选",
      );
      expect(html).toContain(
        language === "en"
          ? `Delete ${geometry} only`
          : geometry === "box"
            ? "仅删除框"
            : "仅删除掩膜",
      );
    }
    s.selected = null;
    const empty = await render();
    expect(empty).toContain('role="toolbar"');
    expect(empty).toContain(language === "en" ? "Object tools" : "对象工具");
    expect(empty).toContain(language === "en" ? "New object" : "新物体");
    expect(empty).not.toContain(
      language === "en" ? "Clear all prompts" : "清空本图提示",
    );
  },
);
