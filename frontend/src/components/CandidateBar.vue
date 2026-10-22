<script setup lang="ts">
import { useProject } from "../stores/project";
import { t, uiError } from "../i18n";
const store = useProject();
function key(event: KeyboardEvent) {
  if (event.isComposing) return;
  event.stopPropagation();
  const session = store.candidates;
  if (!session) return;
  if (event.key === "Escape" && session.phase !== "applying") {
    event.preventDefault();
    store.cancelCandidates();
  } else if (
    session.phase === "ready" &&
    ["ArrowLeft", "ArrowRight"].includes(event.key)
  ) {
    event.preventDefault();
    const count = session.response?.items.length || 1;
    session.active =
      (session.active + count + (event.key === "ArrowRight" ? 1 : -1)) % count;
  } else if (
    event.key === "Enter" &&
    !(event.target as HTMLElement).closest("[data-candidate-action]")
  ) {
    event.preventDefault();
    void store.applyCandidate();
  }
}
</script>
<template>
  <section
    v-if="store.candidates"
    class="mask-candidates"
    tabindex="0"
    :aria-label="t('Mask candidates')"
    @keydown="key"
  >
    <div class="candidate-heading">
      <strong>{{ t("Mask candidates") }}</strong
      ><span class="muted">{{
        t("Preview only · choose one, then Apply")
      }}</span>
    </div>
    <div class="candidate-content">
      <div
        v-if="
          store.candidates.phase === 'ready' ||
          store.candidates.phase === 'applying'
        "
        class="candidate-options"
        role="group"
        :aria-label="t('Candidate choices')"
      >
        <button
          v-for="(item, index) in store.candidates.response?.items"
          :key="index"
          :class="{ active: store.candidates.active === index }"
          :aria-pressed="store.candidates.active === index"
          :disabled="store.candidates.phase === 'applying'"
          @click="store.candidates.active = index"
          :title="
            t('Candidate {number} · predicted quality, not accuracy', {
              number: index + 1,
            })
          "
        >
          <img :src="item.overlay" alt="" /><span
            >{{ t("Candidate {number}", { number: index + 1 })
            }}<small v-if="item.quality != null">{{
              item.quality.toFixed(3)
            }}</small></span
          >
        </button>
      </div>
      <p v-if="store.candidates.phase === 'loading'" role="status">
        {{ t("Generating mask candidates…") }}
      </p>
      <p
        v-if="store.candidates.phase === 'error'"
        class="candidate-error"
        role="alert"
      >
        {{ uiError(store.candidates.error) }}
      </p>
      <div class="candidate-actions">
        <button
          v-if="store.candidates.phase === 'error'"
          data-candidate-action
          @click="store.generateCandidates()"
        >
          {{ t("Retry") }}
        </button>
        <button
          class="primary"
          data-candidate-action
          :disabled="store.candidates.phase !== 'ready'"
          @click="store.applyCandidate()"
        >
          {{
            store.candidates.phase === "applying" ? t("Saving…") : t("Apply")
          }}
        </button>
        <button
          data-candidate-action
          :disabled="store.candidates.phase === 'applying'"
          @click="store.cancelCandidates()"
        >
          {{ t("Cancel") }}
        </button>
      </div>
    </div>
    <p class="candidate-help muted">
      {{ t("Predicted quality · ← → when focused · Enter apply · Esc cancel") }}
    </p>
  </section>
  <p v-if="store.candidateNotice" class="candidate-notice" role="status">
    {{ t(store.candidateNotice) }}
  </p>
</template>
<style scoped>
.mask-candidates {
  flex: none;
  background: #fff;
  border-top: 1px solid var(--line);
  padding: 10px 12px;
  min-width: 0;
  max-height: 35vh;
  overflow: auto;
}
.candidate-heading {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 12px;
  align-items: center;
  font-size: 12px;
}
.candidate-content {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 16px;
  align-items: center;
  margin-top: 8px;
}
.candidate-options {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.candidate-options button {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 5px 8px;
  min-width: 100px;
  background: #f7f9fc;
}
.candidate-options button.active {
  background: #edf2ff;
}
.candidate-options img {
  width: 48px;
  height: 36px;
  object-fit: contain;
  background: #e7ecf3;
  border-radius: 3px;
}
.candidate-options span {
  display: grid;
  text-align: start;
  font-size: 11px;
  gap: 2px;
}
.candidate-options small {
  font-variant-numeric: tabular-nums;
}
.candidate-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-inline-start: auto;
}
.candidate-help {
  font-size: 10px;
  margin: 6px 0 0;
}
.candidate-content p {
  margin: 0;
  flex: 1;
}
.candidate-error {
  color: #a43848;
  overflow-wrap: anywhere;
}
.candidate-notice {
  flex: none;
  margin: 0;
  padding: 6px 12px;
  background: #f3f6ff;
  color: #385991;
  font-size: 11px;
}
</style>
