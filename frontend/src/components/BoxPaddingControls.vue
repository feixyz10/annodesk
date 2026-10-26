<script setup lang="ts">
import { computed } from "vue";
import { t } from "../i18n";
import { useProject } from "../stores/project";
defineProps<{ disabled?: boolean }>();
const store = useProject();
const percent = computed({
  get: () => store.boxPadding.box_padding_ratio * 100,
  set: (value: number) => {
    store.boxPadding.box_padding_ratio = value / 100;
  },
});
</script>
<template>
  <fieldset class="box-padding" :disabled="disabled">
    <legend>{{ t("Mask to box padding") }}</legend>
    <label
      >{{ t("Mode")
      }}<select
        v-model="store.boxPadding.box_padding_mode"
        :disabled="store.boxPadding.box_padding_min"
      >
        <option value="pixels">{{ t("Pixels") }}</option>
        <option value="ratio">{{ t("Ratio") }}</option>
      </select></label
    >
    <label
      >{{ t("Pixels per side")
      }}<input
        v-model.number="store.boxPadding.box_padding_pixels"
        type="number"
        min="0"
        step="1"
        :disabled="
          !store.boxPadding.box_padding_min &&
          store.boxPadding.box_padding_mode !== 'pixels'
        "
    /></label>
    <label
      >{{ t("Percent per side")
      }}<input
        v-model.number="percent"
        type="number"
        min="0"
        step="1"
        :disabled="
          !store.boxPadding.box_padding_min &&
          store.boxPadding.box_padding_mode !== 'ratio'
        "
    /></label>
    <label
      :title="
        t(
          'Use the smaller pixel and ratio padding on each axis; clip to image bounds',
        )
      "
      ><input v-model="store.boxPadding.box_padding_min" type="checkbox" />{{
        t("min (pixels, ratio)")
      }}</label
    >
    <small>{{
      t(
        "Ratio uses the mask bounding box width and height. Zero means no padding.",
      )
    }}</small>
  </fieldset>
</template>
