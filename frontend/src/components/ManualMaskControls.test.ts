import { it, expect, afterEach } from "vitest";
import { createSSRApp } from "vue";
import { createPinia, setActivePinia } from "pinia";
import { renderToString } from "@vue/server-renderer";
import { useProject } from "../stores/project";
import { setLocale } from "../i18n";
import ManualMaskControls from "./ManualMaskControls.vue";
afterEach(() => setLocale("en"));
it.each(["en", "zh-CN"])(
  "renders concise manual parameters in %s without a model",
  async (lang) => {
    setLocale(lang);
    const pinia = createPinia();
    setActivePinia(pinia);
    const s = useProject();
    const render = async () => {
      const app = createSSRApp(ManualMaskControls);
      app.use(pinia);
      return renderToString(app);
    };
    s.tool = "brush";
    let html = await render();
    expect(html).toContain(lang === "en" ? "Brush" : "画笔");
    expect(html).toContain('type="number"');
    expect(html).not.toContain("Segment current");
    s.tool = "polygon";
    html = await render();
    expect(html).toContain(lang === "en" ? "Subtract" : "减去");
    expect(html).toContain(lang === "en" ? "Add" : "添加");
    expect(html).toContain(lang === "en" ? "Finish" : "完成");
    expect(html).not.toContain('type="number"');
  },
);
