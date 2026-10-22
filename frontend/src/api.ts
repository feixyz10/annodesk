import { readPreference } from "./preferences";
export let apiBase = "/api/v1";
export let projectSession = "";
export function setProjectSession(session?: string) {
  projectSession = session || "";
}
export function projectResource(
  path: string,
  session = projectSession,
): string {
  return (
    apiBase +
    path +
    (session
      ? `${path.includes("?") ? "&" : "?"}project_session=${encodeURIComponent(session)}`
      : "")
  );
}
export async function configureApi() {
  const response = await fetch("/ui-config.json", { cache: "no-store" });
  if (response.ok) apiBase = (await response.json()).apiBase;
  apiBase = readPreference("annodesk-api") || apiBase;
}
export async function request<T>(
  path: string,
  method = "GET",
  body?: unknown,
): Promise<T> {
  const response = await fetch(apiBase + path, {
    cache: "no-store",
    method,
    headers: {
      ...(body === undefined ? {} : { "Content-Type": "application/json" }),
      ...(projectSession ? { "X-AnnoDesk-Project": projectSession } : {}),
    },
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
  confidence?: number | null;
  model_class_index?: number | null;
  box_source?: string;
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
  session?: string;
  root: string;
  classes: Category[];
  tags: Category[];
  image_count: number;
  active_models?: Partial<Record<"detection" | "segmentation", string>>;
  model_settings?: Record<string, ModelParameters>;
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

export type Operation = "detection" | "segmentation" | "boxes_from_masks";
export interface ModelParameters {
  model: string;
  operation: Operation;
  device_type: "auto" | "cuda" | "cpu" | "mps";
  devices: string;
  confidence: number;
  iou: number;
  imgsz: number;
  max_det: number;
  model_classes: number[] | null;
  allow_new_classes: boolean;
  write_policy: "fill_empty" | "append";
}
export interface ModelCheck {
  model: string;
  loaded?: boolean;
  device?: string;
  class_names: Record<string, string> | null;
  compatibility: {
    relation: string;
    accepted_classes: number;
    extra_classes: Array<{ index: number; name: string }>;
  } | null;
}
export interface ScopePreview {
  input_total: number;
  total: number;
  counts: Record<string, number>;
  errors: Array<{ image: string; error: string }>;
}
export interface ModelOption {
  id: string;
  name: string;
  backend: string;
  task?: "detection" | "segmentation";
  available: boolean;
  path: string | null;
  error: string | null;
  text_prompts: boolean;
  mask_candidates?: boolean;
}
export interface ModelsConfig {
  config: string;
  default_model: string;
  default_detection_model?: string;
  loaded_model?: string;
  loaded_device?: string;
  models: ModelOption[];
}

export interface MaskCandidate {
  mask: unknown;
  polygons: number[][][];
  quality: number | null;
  overlay: string;
}
export interface MaskCandidates {
  project_id: string;
  image_id: string;
  instance_id: string;
  revision: number;
  image_stamp: string;
  model: string;
  items: MaskCandidate[];
}
