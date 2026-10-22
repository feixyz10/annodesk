<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, ref } from "vue";

// Delegate to document so controls inside drawers and dynamically rendered lists
// share one delay. Keep title declarations as the source of tooltip copy.
const text = ref(""),
  box = ref<HTMLDivElement>(),
  position = ref({ left: "0px", top: "0px" });
let target: Element | null = null,
  timer: ReturnType<typeof setTimeout> | undefined;
const id = "annodesk-tooltip";
function hide() {
  clearTimeout(timer);
  text.value = "";
  if (target) {
    const descriptions = (target.getAttribute("aria-describedby") ?? "")
      .split(" ")
      .filter((v) => v && v !== id);
    if (descriptions.length)
      target.setAttribute("aria-describedby", descriptions.join(" "));
    else target.removeAttribute("aria-describedby");
  }
  target = null;
}
function enter(event: Event) {
  const element =
    event.target instanceof Element
      ? event.target.closest("[title], [data-tooltip], button, [role=button]")
      : null;
  if (element === target || !element) return;
  if (event instanceof PointerEvent && event.buttons) return;
  hide();
  target = element;
  const title = element.getAttribute("title");
  if (title !== null) {
    element.setAttribute("data-tooltip", title);
    element.removeAttribute("title");
  }
  const content =
    element.getAttribute("data-tooltip") ||
    element.getAttribute("aria-label") ||
    element.textContent?.trim();
  if (!content) return;
  timer = setTimeout(async () => {
    if (target !== element || !element.isConnected) return;
    text.value = content;
    const described = element.getAttribute("aria-describedby");
    element.setAttribute(
      "aria-describedby",
      [described, id].filter(Boolean).join(" "),
    );
    await nextTick();
    if (!box.value || target !== element) return;
    const anchor = element.getBoundingClientRect(),
      tooltip = box.value.getBoundingClientRect();
    const left = Math.max(
      8,
      Math.min(
        innerWidth - tooltip.width - 8,
        anchor.left + (anchor.width - tooltip.width) / 2,
      ),
    );
    const below = anchor.bottom + 8;
    position.value = {
      left: `${left}px`,
      top: `${
        below + tooltip.height <= innerHeight - 8
          ? below
          : Math.max(8, anchor.top - tooltip.height - 8)
      }px`,
    };
  }, 150);
}
function leave(event: Event) {
  if (!target) return;
  const next = (event as MouseEvent | FocusEvent).relatedTarget;
  if (next instanceof Node && target.contains(next)) return;
  hide();
}
function dismiss(event: KeyboardEvent) {
  if (event.key === "Escape") hide();
}
onMounted(() => {
  document.addEventListener("pointerover", enter, true);
  document.addEventListener("pointerout", leave, true);
  document.addEventListener("focusin", enter, true);
  document.addEventListener("focusout", leave, true);
  document.addEventListener("pointerdown", hide, true);
  document.addEventListener("keydown", dismiss, true);
  document.addEventListener("scroll", hide, true);
});
onBeforeUnmount(() => {
  hide();
  document.removeEventListener("pointerover", enter, true);
  document.removeEventListener("pointerout", leave, true);
  document.removeEventListener("focusin", enter, true);
  document.removeEventListener("focusout", leave, true);
  document.removeEventListener("pointerdown", hide, true);
  document.removeEventListener("keydown", dismiss, true);
  document.removeEventListener("scroll", hide, true);
});
</script>
<template>
  <Teleport to="body">
    <div
      v-if="text"
      :id="id"
      ref="box"
      role="tooltip"
      class="fast-tooltip"
      :style="position"
    >
      {{ text }}
    </div>
  </Teleport>
</template>
