<script setup lang="ts">
defineProps<{ name: string }>();
const paths: Record<string, string> = {
  trash: "M4 6H20M9 6V3H15V6M6 6L7 21H17L18 6M10 10V17M14 10V17",
  close: "M6 6L18 18M6 18L18 6",
  sidebar: "M3 4H21V20H3ZM15 4V20",
  more: "M5 11H6V12H5ZM11 11H12V12H11ZM17 11H18V12H17Z",
  chevrondown: "M6 9L12 15L18 9",
  chevronup: "M6 15L12 9L18 15",
  promptselect: "M5 3L18 12L12 13L9 20ZM17 4V8M15 6H19",
  mask: "M5 4L14 3L20 9L17 18L9 21L3 14ZM8 10L12 7L16 11L12 16Z",
  eye: "M2 12Q12 0 22 12Q12 24 2 12ZM15 12A3 3 0 1 1 9 12A3 3 0 1 1 15 12",
  eyeoff:
    "M3 3L21 21M2 12Q7 5 11 6M15 7Q19 9 22 12Q18 17 14 18M10 18Q6 17 2 12",
  lock: "M7 10V7A5 5 0 0 1 17 7V10M5 10H19V21H5ZM12 14V17",
  unlock: "M7 10V7A5 5 0 0 1 17 7M5 10H19V21H5ZM12 14V17",
  undo: "M9 5L4 10L9 15M4 10H14A6 6 0 0 1 14 22",
  redo: "M15 5L20 10L15 15M20 10H10A6 6 0 0 0 10 22",
  help: "M9 9A3 3 0 0 1 15 9C15 11 12 11 12 14M12 17V18",
  select: "M5 3 18 12 12 13 9 20Z",
  box: "M4 5H20V19H4Z",
  positive: "M8 12H16M12 8V16",
  negative: "M8 12H16",
  promptbox: "M9 4H4V9M15 4H20V9M4 15V20H9M15 20H20V15M9 12H15M12 9V15",
  text: "M4 5H20M12 5V20M8 20H16",
  pan: "M8 12V6A1.5 1.5 0 0 1 11 6V11V4A1.5 1.5 0 0 1 14 4V11V6A1.5 1.5 0 0 1 17 6V12V9A1.5 1.5 0 0 1 20 9V16C20 22 12 23 8 18L4 13Q3 10 6 11Z",
  fit: "M4 9V4H9M15 4H20V9M4 15V20H9M15 20H20V15",
  plus: "M7 10H13M10 7V13M15 15 21 21",
  minus: "M7 10H13M15 15 21 21",
};
</script>
<template>
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <circle v-if="['plus', 'minus'].includes(name)" cx="10" cy="10" r="6" />
    <circle
      v-if="['positive', 'negative', 'help'].includes(name)"
      cx="12"
      cy="12"
      r="8"
    />
    <path :d="paths[name]" />
  </svg>
</template>
