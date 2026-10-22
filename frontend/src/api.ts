export let apiBase = "/api/v1";
export async function configureApi() {
  const response = await fetch("/ui-config.json", { cache: "no-store" });
  if (response.ok) apiBase = (await response.json()).apiBase;
  apiBase = localStorage.getItem("annodesk-api") || apiBase;
}
export async function request<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const response = await fetch(apiBase + path, {
    cache: "no-store",
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!response.ok) {
    let detail;
    try {
      detail = (await response.json()).detail;
    } catch {
      detail = response.statusText;
    }
    throw new Error(
      typeof detail === "string" ? detail : JSON.stringify(detail),
    );
  }
  return await response.json();
}
export interface Category {
  id: string;
  name: string;
  color: string;
  index?: number;
}
export interface ImageItem {
  id: string;
  path: string;
}
export interface PromptPoint {
  x: number;
  y: number;
  positive: boolean;
}
export interface Instance {
  id: string;
  class_id: string | null;
  box: number[] | null;
  polygons: number[][][];
  mask: unknown | null;
  points: PromptPoint[];
  prompt_box: number[] | null;
  hidden: boolean;
  locked: boolean;
  source: string;
}
export interface Annotation {
  revision: number;
  instances: Instance[];
  detection_review: "pending" | "ok" | "uncertain";
  segmentation_review: "pending" | "ok" | "uncertain";
  excluded: boolean;
  tags: string[];
  notes: string;
  explicit_empty: Record<string, boolean>;
  width: number;
  height: number;
}
export interface ProjectMeta {
  id: string;
  root: string;
  classes: Category[];
  tags: Category[];
  image_count: number;
}
export function instance(
  category: string | null,
  box: number[] | null = null,
): Instance {
  return {
    id: crypto.randomUUID(),
    class_id: category,
    box,
    polygons: [],
    mask: null,
    points: [],
    prompt_box: null,
    hidden: false,
    locked: false,
    source: "manual",
  };
}

export interface ModelOption {
  id: string;
  name: string;
  backend: string;
  available: boolean;
  path: string | null;
  error: string | null;
  text_prompts: boolean;
}
export interface ModelsConfig {
  config: string;
  default_model: string;
  models: ModelOption[];
}
