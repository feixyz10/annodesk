<script setup lang="ts">
defineProps<{ name: string }>();
const paths: Record<string, string> = {
  help: "M9 9A3 3 0 0 1 15 9C15 11 12 11 12 14M12 17V18",
  select: "M5 3 18 12 12 13 9 20Z",
  box: "M4 5H20V19H4Z",
  positive: "M8 12H16M12 8V16",
  negative: "M8 12H16",
  promptbox: "M4 4H20V20H4ZM8 12 11 15 16 9",
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
