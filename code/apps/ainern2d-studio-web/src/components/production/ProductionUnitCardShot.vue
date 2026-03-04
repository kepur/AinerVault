<template>
  <NCard class="unit-card shot-card" size="small" :title="unit.unit_ref_id">
    <NSpace align="center">
      <NText depth="3">Kind: {{ unit.unit_kind }}</NText>
      <NTag :type="statusType" size="small" :bordered="false">{{ unit.status }}</NTag>
    </NSpace>
    <NText depth="3">Time: {{ unit.planned_start_ms ?? 0 }} - {{ unit.planned_end_ms ?? 0 }} ms</NText>
    <NText depth="3">Attempts: {{ unit.attempt_count }}/{{ unit.max_attempts }}</NText>
    <NText v-if="unit.last_error_message" depth="3">Error: {{ unit.last_error_message }}</NText>
    <NSpace>
      <NButton size="tiny" type="primary" @click="emit('run', unit.unit_id)">Generate</NButton>
      <NButton size="tiny" type="warning" @click="emit('retry', unit.unit_id)">Regenerate</NButton>
      <NButton size="tiny" @click="emit('patch', unit.unit_id)">Params</NButton>
      <NButton size="tiny" @click="emit('preview', unit.unit_id)">Preview</NButton>
    </NSpace>
  </NCard>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { NButton, NCard, NSpace, NText, NTag } from "naive-ui";

const props = defineProps<{
  unit: {
    unit_id: string;
    unit_ref_id: string;
    unit_kind: string;
    status: string;
    planned_start_ms?: number | null;
    planned_end_ms?: number | null;
    attempt_count: number;
    max_attempts: number;
    last_error_message?: string | null;
  };
}>();

const emit = defineEmits<{
  (event: "run", unitId: string): void;
  (event: "retry", unitId: string): void;
  (event: "patch", unitId: string): void;
  (event: "preview", unitId: string): void;
}>();

const statusType = computed<"default" | "success" | "warning" | "error" | "info">(() => {
  if (props.unit.status === "success") return "success";
  if (props.unit.status === "failed") return "error";
  if (props.unit.status === "running" || props.unit.status === "queued") return "warning";
  if (props.unit.status === "blocked") return "info";
  return "default";
});
</script>

<style scoped>
.unit-card {
  background: #111827;
  border: 1px solid #1f2937;
}
.shot-card {
  border-left: 4px solid #3b82f6;
}
</style>
