import { afterEach, describe, expect, it, vi } from "vitest";
import { computed, createSSRApp } from "vue";
import { createPinia, setActivePinia } from "pinia";
import { renderToString } from "@vue/server-renderer";
import ts from "typescript";
import { parse as parseSfc } from "@vue/compiler-sfc";
import { baseParse, NodeTypes } from "@vue/compiler-dom";
import {
  t,
  locale,
  setLocale,
  resolveLocale,
  messages,
  taskLabel,
  statusLabel,
  uiError,
} from "./i18n";
import { useProject } from "./stores/project";
import ClassPalette from "./components/ClassPalette.vue";
import { reviewStates } from "./review";

afterEach(() => setLocale("en"));
describe("interface languages", () => {
  it("switches reactive labels and interpolated counts without changing enums", () => {
    const label = computed(() =>
      t("All project images ({count})", { count: 24 }),
    );
    expect(label.value).toBe("All project images (24)");
    setLocale("zh-CN");
    expect(label.value).toBe("全部项目图片（24）");
    expect(taskLabel("detection")).toBe("检测");
    expect(statusLabel("pending")).toBe("未审核");
    expect(reviewStates[0].value).toBe("pending");
    setLocale("en");
    expect(label.value).toBe("All project images (24)");
  });
  it("persists the selection and tolerates blocked browser storage", () => {
    const values = new Map<string, string>();
    vi.stubGlobal("localStorage", {
      getItem: (key: string) => values.get(key),
      setItem: (key: string, value: string) => values.set(key, value),
    });
    setLocale("zh-CN");
    expect(values.get("annodesk.locale")).toBe("zh-CN");
    vi.stubGlobal("localStorage", {
      setItem: () => {
        throw new Error("Storage blocked");
      },
    });
    expect(() => setLocale("en")).not.toThrow();
    vi.unstubAllGlobals();
  });
  it("falls back safely and preserves raw diagnostics", () => {
    expect(resolveLocale("unexpected")).toBe("en");
    setLocale("zh-CN");
    expect(t("Untranslated future message")).toBe(
      "Untranslated future message",
    );
    expect(
      uiError("Error: Clipboard unavailable; select and copy the log text."),
    ).toContain("剪贴板");
    expect(
      uiError(
        "Error: Project changed in another browser; reopen the intended project",
      ),
    ).toBe("项目已在另一页面切换，请重新打开目标项目");
    expect(uiError("checkpoint unavailable: /srv/model/best.pt")).toBe(
      "checkpoint unavailable: /srv/model/best.pt",
    );
  });
  it("translates the palette while preserving user class names and selection", async () => {
    const pinia = createPinia();
    setActivePinia(pinia);
    const store = useProject();
    store.meta = {
      id: "project",
      root: "/tmp/project",
      image_count: 0,
      classes: [
        { id: "user-class", index: 7, name: "Classes", color: "#336699" },
      ],
      tags: [],
    };
    store.defaultClass = "user-class";
    const before = JSON.stringify(store.meta);
    setLocale("zh-CN");
    const html = await renderToString(createSSRApp(ClassPalette).use(pinia));
    expect(html).toContain("类别面板");
    expect(html).toContain("搜索类别");
    expect(html).toContain("Classes");
    expect(JSON.stringify(store.meta)).toBe(before);
    expect(store.defaultClass).toBe("user-class");
  });
});

describe("translation coverage", () => {
  it("covers static translation calls and preserves interpolation placeholders", () => {
    const sources = import.meta.glob<string>(
      ["./App.vue", "./i18n.ts", "./tasks.ts", "./components/*.vue"],
      { query: "?raw", import: "default", eager: true },
    );
    const keys = new Set<string>();
    function collect(source: string) {
      const ast = ts.createSourceFile(
        "message.ts",
        source,
        ts.ScriptTarget.Latest,
        true,
      );
      function visit(node: ts.Node) {
        if (
          ts.isCallExpression(node) &&
          node.expression.getText(ast) === "t" &&
          node.arguments[0] &&
          ts.isStringLiteral(node.arguments[0])
        )
          keys.add(node.arguments[0].text);
        ts.forEachChild(node, visit);
      }
      visit(ast);
    }
    for (const [path, source] of Object.entries(sources)) {
      if (!path.endsWith(".vue")) {
        collect(source);
        continue;
      }
      const { descriptor } = parseSfc(source);
      collect(descriptor.scriptSetup?.content || "");
      if (descriptor.template) {
        const template = baseParse(descriptor.template.content);
        function visit(node: any) {
          if (node.type === NodeTypes.INTERPOLATION)
            collect(node.content.content);
          if (node.type === NodeTypes.ELEMENT)
            for (const prop of node.props)
              if (prop.type === NodeTypes.DIRECTIVE && prop.exp)
                collect(prop.exp.content);
          for (const child of node.children || []) visit(child);
        }
        visit(template);
      }
    }
    for (const state of reviewStates) {
      keys.add(state.label);
      keys.add(state.description);
    }
    expect(keys.size).toBeGreaterThan(200);
    expect([...keys].filter((key) => !Object.hasOwn(messages, key))).toEqual(
      [],
    );
    for (const [english, chinese] of Object.entries(messages)) {
      const placeholders = (value: string) =>
        [...value.matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort();
      expect(chinese.trim(), english).not.toBe("");
      expect(placeholders(chinese), english).toEqual(placeholders(english));
    }
  });
});
