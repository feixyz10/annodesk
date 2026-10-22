<script setup lang="ts">
import { computed, ref, watch, nextTick } from "vue";
import { type Job, elapsed } from "../tasks";
import TaskProgress from "./TaskProgress.vue";
const props = defineProps<{
  show: boolean;
  jobs: Job[];
  images: Array<{ id: string; path: string }>;
}>();
const emit = defineEmits<{
  "update:show": [boolean];
  cancel: [id: string];
  resume: [id: string];
  logs: [];
}>();
const expanded = ref("");
const panel = ref<HTMLElement>();
let previousFocus: HTMLElement | null = null;
watch(
  () => props.show,
  (show) => {
    if (show) {
      previousFocus = document.activeElement as HTMLElement;
      void nextTick(() => panel.value?.focus());
    } else if (previousFocus?.isConnected) previousFocus.focus();
  },
);
function title(job: Job) {
  return job.kind === "export"
    ? "Export"
    : job.kind === "detection"
      ? "Batch detection"
      : job.kind === "boxes_from_masks"
        ? "Boxes from masks"
        : "Batch segmentation";
}

const sorted = computed(() => [...props.jobs].reverse());
let latestId = "",
  activeId = "";
watch(
  () => props.jobs,
  (jobs) => {
    const latest = jobs.at(-1)?.id || "";
    const active = jobs.find((j) => j.status === "running")?.id || "";
    if (
      (active && active !== activeId) ||
      latest !== latestId ||
      !jobs.some((j) => j.id === expanded.value)
    )
      expanded.value = active || latest;
    latestId = latest;
    activeId = active;
  },
);
function path(id: string) {
  return props.images.find((i) => i.id === id)?.path || id;
}
function toggle(event: Event, id: string) {
  if ((event.target as HTMLDetailsElement).open) expanded.value = id;
}
</script>
<template>
  <Teleport to="body">
    <section
      v-if="show"
      ref="panel"
      tabindex="-1"
      role="dialog"
      aria-modal="false"
      aria-labelledby="tasks-title"
      class="task-window"
      @keydown.esc.stop="emit('update:show', false)"
    >
      <div class="task-window-heading">
        <h2 id="tasks-title">Tasks</h2>
        <button
          aria-label="Close tasks"
          title="Close task window; processing continues"
          @click="emit('update:show', false)"
        >
          Close
        </button>
      </div>
      <div class="task-window-body">
        <p class="muted">
          Closing this window keeps tasks running. Reopen Tasks in the toolbar
          to check progress.
        </p>
        <p v-if="!jobs.length">
          No tasks yet. Start Batch processing or Export from the toolbar.
        </p>
        <details
          v-for="job in sorted"
          :key="job.id"
          :open="job.id === expanded"
          @toggle="toggle($event, job.id)"
          class="task-card"
        >
          <summary>
            <strong>{{ title(job) }}</strong
            ><span class="task-status" :class="job.status">{{
              job.status
            }}</span
            ><span>{{ job.completed }}/{{ job.total }} finished</span>
          </summary>
          <div class="task-body">
            <dl class="task-meta">
              <dt>Started</dt>
              <dd>
                {{
                  job.started_at
                    ? new Date(job.started_at * 1000).toLocaleString()
                    : "Earlier session"
                }}
              </dd>
              <dt>Elapsed</dt>
              <dd>{{ elapsed(job) }}</dd>
              <dt>Task ID</dt>
              <dd>{{ job.id }}</dd>
            </dl>
            <TaskProgress
              :completed="job.completed"
              :total="job.total"
              :phase="job.phase || job.status"
              :running="job.status === 'running'"
            />
            <div v-if="job.kind !== 'export'" class="task-counts">
              <span
                ><b>{{ job.processed || 0 }}</b
                >Succeeded</span
              ><span
                ><b>{{ job.failed.length }}</b
                >Failed</span
              ><span
                ><b>{{ job.skipped }}</b
                >Skipped</span
              ><span
                ><b>{{ job.remaining?.length || 0 }}</b
                >Remaining</span
              >
            </div>
            <p
              v-if="job.kind === 'detection' || job.kind === 'boxes_from_masks'"
              class="muted"
            >
              {{ job.boxes_added || 0 }} boxes added ·
              {{ job.boxes_updated || 0 }} boxes updated ·
              {{ job.detections_discarded || 0 }} detections discarded ·
              {{ job.classes_added || 0 }} classes added
            </p>
            <p v-if="job.kind === 'export'">
              {{ job.completed }}/{{ job.total }} images inspected. Exported and
              skipped totals appear in the final report.
            </p>
            <p v-if="!job.total && job.status === 'complete'">
              {{
                job.kind === "export"
                  ? "No images to export"
                  : "No images require processing"
              }}
            </p>
            <section v-if="job.model || job.request" class="task-section">
              <h3>Execution settings</h3>
              <dl class="task-meta">
                <template v-if="job.kind !== 'export'"
                  ><dt>Model</dt>
                  <dd>
                    {{
                      job.kind === "boxes_from_masks"
                        ? "None (CPU geometry)"
                        : job.model || job.request?.model || "Default"
                    }}
                  </dd>
                  <dt v-if="job.plan">Devices</dt>
                  <dd v-if="job.plan">
                    {{ job.plan.devices.join(", ") }}
                  </dd></template
                ><template v-else
                  ><dt>Task / format</dt>
                  <dd>
                    {{ job.request?.task }} / {{ job.request?.format }}
                  </dd></template
                >
                <template v-if="job.request?.review_states"
                  ><dt>Review states</dt>
                  <dd>{{ job.request.review_states.join(", ") }}</dd></template
                >
                <template v-if="job.kind === 'detection'">
                  <dt>Thresholds</dt>
                  <dd>
                    Confidence {{ job.request?.confidence }} · NMS IoU
                    {{ job.request?.iou }}
                  </dd>
                  <dt>Prediction</dt>
                  <dd>
                    Image size {{ job.request?.imgsz }} · Max detections
                    {{ job.request?.max_det }}
                  </dd>
                  <dt>Classes</dt>
                  <dd>
                    {{
                      job.request?.model_classes?.join(", ") ||
                      "All model classes"
                    }}
                  </dd>
                  <dt>Write policy</dt>
                  <dd>{{ job.request?.write_policy }}</dd>
                  <dt>New classes</dt>
                  <dd>
                    {{
                      job.request?.allow_new_classes
                        ? "Add when detected"
                        : "Discard outside project"
                    }}
                  </dd>
                </template>
                <template v-if="job.kind === 'boxes_from_masks'"
                  ><dt>Existing boxes</dt>
                  <dd>
                    {{
                      job.request?.recalculate_boxes
                        ? "Recalculate unlocked"
                        : "Preserve"
                    }}
                  </dd></template
                >
                <template v-if="job.request?.operation"
                  ><dt>Image range</dt>
                  <dd>
                    {{
                      job.request?.image_ids
                        ? job.request.image_ids.length + " selected images"
                        : "All project images at task creation"
                    }}
                  </dd></template
                >
              </dl>
            </section>
            <section v-if="job.plan" class="task-section">
              <h3>Workers · {{ job.plan.workers.length }}</h3>
              <div class="worker-table">
                <div
                  v-for="(device, index) in job.plan.workers"
                  :key="index"
                  class="worker-row"
                >
                  <strong>Worker {{ index }}</strong
                  ><span>{{ device }}</span
                  ><template
                    v-if="
                      job.active_workers?.some((w) => w.worker_id === index)
                    "
                    ><div
                      v-for="worker in job.active_workers.filter(
                        (w) => w.worker_id === index,
                      )"
                      :key="worker.worker_id"
                      class="worker-image"
                    >
                      <span>{{ path(worker.image) }}</span
                      ><span>{{ worker.elapsed_seconds }}s</span>
                    </div></template
                  ><span v-else class="muted">{{
                    job.status !== "running"
                      ? "Stopped"
                      : job.phase === "loading"
                        ? "Loading model…"
                        : "Idle"
                  }}</span>
                </div>
              </div>
            </section>
            <section v-if="job.error || job.failed.length" class="task-section">
              <h3>Errors · {{ job.failed.length }}</h3>
              <p v-if="job.error" class="task-error">{{ job.error }}</p>
              <div class="task-failures">
                <div v-for="(failure, index) in job.failed" :key="index">
                  <strong>{{ path(failure.image) }}</strong>
                  <p>{{ failure.error }}</p>
                </div>
              </div>
            </section>
            <section v-if="job.output" class="task-section">
              <h3>Saved on the backend</h3>
              <p class="task-output">{{ job.output }}</p>
            </section>
            <div class="task-actions">
              <button
                v-if="job.status === 'running'"
                @click="emit('cancel', job.id)"
              >
                Cancel after active images</button
              ><button
                v-else-if="job.kind !== 'export' && job.remaining?.length"
                @click="emit('resume', job.id)"
              >
                Resume pending images</button
              ><button @click="emit('logs')">View logs</button>
            </div>
            <p v-if="job.kind !== 'export'" class="muted">
              Finished = succeeded + failed. Success is counted after saving.
              Generated annotations still require human review.
            </p>
          </div>
        </details>
      </div>
    </section>
  </Teleport>
</template>
<style scoped>
.task-window {
  position: fixed;
  z-index: 1500;
  top: 10vh;
  left: 50%;
  transform: translateX(-50%);
  width: 900px;
  max-width: 90vw;
  height: 80vh;
  min-width: 320px;
  min-height: 280px;
  background: white;
  border: 1px solid #d7dfe9;
  border-radius: 12px;
  box-shadow: 0 14px 48px #15243c35;
  display: flex;
  flex-direction: column;
  resize: both;
  overflow: hidden;
}
.task-window-heading {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 22px;
  border-bottom: 1px solid var(--line);
  flex: none;
}
.task-window-heading h2 {
  margin: 0;
  font-size: 17px;
}
.task-window-body {
  padding: 6px 22px 20px;
  overflow: auto;
  flex: 1;
  min-height: 0;
}

.task-card {
  margin: 16px 0;
  border: 1px solid var(--line);
  border-radius: 10px;
  background: #fff;
}
summary {
  padding: 14px;
  cursor: pointer;
  display: flex;
  flex-wrap: wrap;
  gap: 8px 14px;
  align-items: center;
  font-size: 12px;
}
summary::before {
  content: "▸";
}
details[open] > summary::before {
  content: "▾";
}
.task-body {
  padding: 0 18px 16px;
}
.task-meta {
  display: grid;
  grid-template-columns: 90px minmax(0, 1fr);
  gap: 7px 12px;
  font-size: 12px;
  margin: 12px 0 18px;
}
.task-meta dt {
  color: #738094;
}
.task-meta dd {
  margin: 0;
  overflow-wrap: anywhere;
}
.task-status {
  border-radius: 20px;
  padding: 2px 8px;
  background: #f1f4f8;
}
.running {
  background: #edf2ff;
  color: #315fe9;
}
.failed {
  background: #fff0f1;
  color: #a43848;
}
.complete {
  background: #eaf5ef;
  color: #24835d;
}
.task-counts {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 8px;
  padding: 14px 0;
}
.task-counts span {
  display: grid;
  gap: 2px;
  color: #738094;
  font-size: 11px;
}
.task-counts b {
  color: #283445;
  font-size: 22px;
  font-variant-numeric: tabular-nums;
}
.task-section {
  border-top: 1px solid var(--line);
  margin-top: 16px;
  padding-top: 16px;
}
.task-section h3 {
  margin-bottom: 12px;
}
.worker-row {
  display: grid;
  grid-template-columns: 86px 70px minmax(0, 1fr);
  align-items: start;
  gap: 10px;
  padding: 10px 0;
  font-size: 12px;
  border-bottom: 1px solid #f1f4f8;
}
.worker-image {
  display: flex;
  gap: 10px;
  justify-content: space-between;
  overflow-wrap: anywhere;
}
.worker-image span:first-child {
  min-width: 0;
}
.task-failures {
  max-height: 320px;
  overflow: auto;
}
.task-failures div {
  background: #fff5f5;
  border-radius: 6px;
  padding: 10px;
  margin: 8px 0;
  font-size: 12px;
  overflow-wrap: anywhere;
}
.task-failures p {
  margin-bottom: 0;
}
.task-error {
  color: #a43848;
  overflow-wrap: anywhere;
}
.task-output {
  background: #f6f8fb;
  padding: 12px;
  border-radius: 6px;
  overflow-wrap: anywhere;
}
.task-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 18px;
}
</style>
