<script setup lang="ts">
import { t, statusLabel, taskLabel, formatDate } from "../i18n";
import { computed, ref, watch } from "vue";
import { NModal } from "naive-ui";
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
  <NModal
    :show="show"
    @update:show="emit('update:show', $event)"
    preset="card"
    :title="t('Tasks')"
    class="task-window"
    style="
      width: 900px;
      max-width: 92vw;
      max-height: 85vh;
      overflow: hidden;
      resize: both;
    "
    content-style="overflow:auto;min-height:0"
  >
    <div class="task-window-body">
      <p class="muted">
        {{
          t(
            "Closing this window keeps tasks running. Reopen Tasks in the toolbar to check progress.",
          )
        }}
      </p>
      <p v-if="!jobs.length">
        {{
          t("No tasks yet. Start Batch processing or Export from the toolbar.")
        }}
      </p>
      <details
        v-for="job in sorted"
        :key="job.id"
        :open="job.id === expanded"
        @toggle="toggle($event, job.id)"
        class="task-card"
      >
        <summary>
          <strong>{{ t(title(job)) }}</strong
          ><span class="task-status" :class="job.status">{{
            statusLabel(job.status)
          }}</span
          ><span>{{
            t("{completed}/{total} finished", {
              completed: job.completed,
              total: job.total,
            })
          }}</span>
        </summary>
        <div class="task-body">
          <dl class="task-meta">
            <dt>{{ t("Started") }}</dt>
            <dd>
              {{
                job.started_at
                  ? formatDate(job.started_at)
                  : t("Earlier session")
              }}
            </dd>
            <dt>{{ t("Elapsed") }}</dt>
            <dd>{{ elapsed(job) }}</dd>
            <dt>{{ t("Task ID") }}</dt>
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
              >{{ t("Succeeded") }}</span
            ><span
              ><b>{{ job.failed.length }}</b
              >{{ t("Failed") }}</span
            ><span
              ><b>{{ job.skipped }}</b
              >{{ t("Skipped") }}</span
            ><span
              ><b>{{ job.remaining?.length || 0 }}</b
              >{{ t("Remaining") }}</span
            >
          </div>
          <p
            v-if="job.kind === 'detection' || job.kind === 'boxes_from_masks'"
            class="muted"
          >
            {{
              t(
                "{added} boxes added · {updated} boxes updated · {discarded} detections discarded · {classes} classes added",
                {
                  added: job.boxes_added || 0,
                  updated: job.boxes_updated || 0,
                  discarded: job.detections_discarded || 0,
                  classes: job.classes_added || 0,
                },
              )
            }}
          </p>
          <p v-if="job.kind === 'export' && job.status === 'complete'">
            {{
              t("{exported} images exported · {skipped} skipped", {
                exported: job.processed || 0,
                skipped: job.skipped || 0,
              })
            }}
          </p>
          <p v-else-if="job.kind === 'export'">
            {{ job.completed }}/{{ job.total }}
            {{
              t(
                "images inspected. Exported and skipped totals appear in the final report.",
              )
            }}
          </p>
          <p v-if="!job.total && job.status === 'complete'">
            {{
              job.kind === "export"
                ? t("No images to export")
                : t("No images require processing")
            }}
          </p>
          <section v-if="job.model || job.request" class="task-section">
            <h3>{{ t("Execution settings") }}</h3>
            <dl class="task-meta">
              <template v-if="job.kind !== 'export'"
                ><dt>{{ t("Model") }}</dt>
                <dd>
                  {{
                    job.kind === "boxes_from_masks"
                      ? t("None (CPU geometry)")
                      : job.model || job.request?.model || t("Default")
                  }}
                </dd>
                <dt v-if="job.plan">{{ t("Devices") }}</dt>
                <dd v-if="job.plan">
                  {{ job.plan.devices.join(", ") }}
                </dd></template
              ><template v-else
                ><dt>{{ t("Task / format") }}</dt>
                <dd>
                  {{ taskLabel(job.request?.task || "") }} /
                  {{ job.request?.format }}
                </dd></template
              >
              <template v-if="job.request?.review_states"
                ><dt>{{ t("Review states") }}</dt>
                <dd>
                  {{ job.request.review_states.map(statusLabel).join(" · ") }}
                </dd></template
              >
              <template v-if="job.kind === 'detection'">
                <dt>{{ t("Thresholds") }}</dt>
                <dd>
                  {{ t("Confidence") }} {{ job.request?.confidence }}
                  {{ t("· NMS IoU") }}
                  {{ job.request?.iou }}
                </dd>
                <dt>{{ t("Prediction") }}</dt>
                <dd>
                  {{ t("Image size") }} {{ job.request?.imgsz }}
                  {{ t("· Max detections") }}
                  {{ job.request?.max_det }}
                </dd>
                <dt>{{ t("Classes") }}</dt>
                <dd>
                  {{
                    job.request?.model_classes?.join(", ") ||
                    t("All model classes")
                  }}
                </dd>
                <dt>{{ t("Write policy") }}</dt>
                <dd>{{ statusLabel(job.request?.write_policy || "") }}</dd>
                <dt>{{ t("New classes") }}</dt>
                <dd>
                  {{
                    job.request?.allow_new_classes
                      ? t("Add when detected")
                      : t("Discard outside project")
                  }}
                </dd>
              </template>
              <template v-if="job.kind === 'boxes_from_masks'"
                ><dt>{{ t("Existing boxes") }}</dt>
                <dd>
                  {{
                    job.request?.recalculate_boxes
                      ? t("Recalculate unlocked")
                      : t("Preserve")
                  }}
                </dd></template
              >
              <template v-if="job.request?.operation"
                ><dt>{{ t("Image range") }}</dt>
                <dd>
                  {{
                    job.request?.image_ids
                      ? t("{count} selected images", {
                          count: job.request.image_ids.length,
                        })
                      : t("All project images at task creation")
                  }}
                </dd></template
              >
            </dl>
          </section>
          <section v-if="job.plan" class="task-section">
            <h3>{{ t("Workers ·") }} {{ job.plan.workers.length }}</h3>
            <div class="worker-table">
              <div
                v-for="(device, index) in job.plan.workers"
                :key="index"
                class="worker-row"
              >
                <strong>{{ t("Worker") }} {{ index }}</strong
                ><span>{{ device }}</span
                ><template
                  v-if="job.active_workers?.some((w) => w.worker_id === index)"
                  ><div
                    v-for="worker in job.active_workers.filter(
                      (w) => w.worker_id === index,
                    )"
                    :key="worker.worker_id"
                    class="worker-image"
                  >
                    <span>{{ path(worker.image) }}</span
                    ><span>{{ worker.elapsed_seconds }}{{ t("s") }}</span>
                  </div></template
                ><span v-else class="muted">{{
                  job.status !== "running"
                    ? t("Stopped")
                    : job.phase === "loading"
                      ? t("Loading model…")
                      : t("Idle")
                }}</span>
              </div>
            </div>
          </section>
          <section v-if="job.error || job.failed.length" class="task-section">
            <h3>{{ t("Errors ·") }} {{ job.failed.length }}</h3>
            <p v-if="job.error" class="task-error">{{ job.error }}</p>
            <div class="task-failures">
              <div v-for="(failure, index) in job.failed" :key="index">
                <strong>{{ path(failure.image) }}</strong>
                <p>{{ failure.error }}</p>
              </div>
            </div>
          </section>
          <section v-if="job.output" class="task-section">
            <h3>{{ t("Saved on the backend") }}</h3>
            <p class="task-output">{{ job.output }}</p>
          </section>
          <div class="task-actions">
            <button
              v-if="job.status === 'running'"
              @click="emit('cancel', job.id)"
            >
              {{ t("Cancel after active images") }}</button
            ><button
              v-else-if="job.kind !== 'export' && job.remaining?.length"
              @click="emit('resume', job.id)"
            >
              {{ t("Resume pending images") }}</button
            ><button @click="emit('logs')">{{ t("View logs") }}</button>
          </div>
          <p v-if="job.kind !== 'export'" class="muted">
            {{
              t(
                "Finished = succeeded + failed. Success is counted after saving. Generated annotations still require human review.",
              )
            }}
          </p>
        </div>
      </details>
    </div>
  </NModal>
</template>
<style scoped>
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
