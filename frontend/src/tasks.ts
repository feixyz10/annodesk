export interface Job {
  id: string;
  kind?: string;
  status: string;
  phase?: string;
  completed: number;
  processed?: number;
  boxes_added?: number;
  boxes_updated?: number;
  detections_discarded?: number;
  classes_added?: number;
  skipped: number;
  total: number;
  remaining: string[];
  failed: Array<{ image: string; error: string }>;
  error?: string;
  output?: string;
  started_at?: number;
  elapsed_seconds?: number;
  request?: {
    model?: string;
    task?: string;
    format?: string;
    operation?: string;
    imgsz?: number;
    max_det?: number;
    model_classes?: number[] | null;
    recalculate_boxes?: boolean;
    image_ids?: string[] | null;
    confidence?: number;
    iou?: number;
    write_policy?: string;
    allow_new_classes?: boolean;
    review_states?: string[];
  };
  model?: string;
  plan?: { device_type: string; devices: string[]; workers: string[] };
  active_workers?: Array<{
    worker_id: number;
    device: string;
    image: string;
    elapsed_seconds: number;
  }>;
}
export function elapsed(job: Job) {
  const seconds = Math.max(
    0,
    Math.floor(
      job.status === "running" && job.started_at
        ? Date.now() / 1000 - job.started_at
        : job.elapsed_seconds || 0,
    ),
  );
  return `${Math.floor(seconds / 60)}m ${seconds % 60}s`;
}
export function isPreparing(job: Job) {
  return ["preparing", "preflight", "loading", "packaging"].includes(
    job.phase || "",
  );
}
