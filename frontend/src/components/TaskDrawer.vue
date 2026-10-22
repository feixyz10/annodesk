<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { NDrawer, NDrawerContent } from "naive-ui";
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
  <NDrawer
    :show="show"
    @update:show="emit('update:show', $event)"
    placement="right"
    :width="600"
    resizable
    style="max-width: 100vw"
  >
    <NDrawerContent title="Tasks" closable>
      <p class="muted">
        Closing this drawer keeps tasks running. Reopen Tasks in the toolbar to
        check progress.
      </p>
      <p v-if="!jobs.length">
        No tasks yet. Start Batch segmentation or Export from the toolbar.
      </p>
      <details
        v-for="job in sorted"
        :key="job.id"
        :open="job.id === expanded"
        @toggle="toggle($event, job.id)"
        class="task-card"
      >
        <summary>
          <strong>{{
            job.kind === "export" ? "Export" : "Batch segmentation"
          }}</strong
          ><span class="task-status" :class="job.status">{{ job.status }}</span
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
          <p v-else>
            {{ job.completed }}/{{ job.total }} images inspected. Exported and
            skipped totals appear in the final report.
          </p>
          <p v-if="!job.total && job.status === 'complete'">
            {{
              job.kind === "export"
                ? "No images to export"
                : "No images require segmentation"
            }}
          </p>
          <section v-if="job.model || job.request" class="task-section">
            <h3>Execution settings</h3>
            <dl class="task-meta">
              <template v-if="job.kind !== 'export'"
                ><dt>Model</dt>
                <dd>{{ job.model || job.request?.model || "Default" }}</dd>
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
                  v-if="job.active_workers?.some((w) => w.worker_id === index)"
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
            Generated masks still require human review.
          </p>
        </div>
      </details>
    </NDrawerContent>
  </NDrawer>
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
