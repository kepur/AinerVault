<template>
  <NCard class="unit-card dialogue-card" size="small" :title="unit.unit_ref_id">
    <NSpace align="center">
      <NText depth="3">Dialogue Unit</NText>
      <NTag :type="statusType" size="small" :bordered="false">{{ unit.status }}</NTag>
    </NSpace>
    <NText depth="3">Time: {{ unit.planned_start_ms ?? 0 }} - {{ unit.planned_end_ms ?? 0 }} ms</NText>
    <NText depth="3">Attempts: {{ unit.attempt_count }}/{{ unit.max_attempts }}</NText>
    <NProgress type="line" :percentage="statusPercent" :show-indicator="false" />
    <NSpace>
      <NButton size="tiny" type="primary" @click="emit('run', unit.unit_id)">Generate</NButton>
      <NButton size="tiny" type="warning" @click="emit('retry', unit.unit_id)">Regenerate</NButton>
      <NButton size="tiny" @click="emit('patch', unit.unit_id)">Voice/Patch</NButton>
      <NButton size="tiny" @click="emit('preview', unit.unit_id)">Play</NButton>
    </NSpace>
  </NCard>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { NButton, NCard, NSpace, NText, NProgress, NTag } from "naive-ui";

const props = defineProps<{
  unit: {
    unit_id: string;
    unit_ref_id: string;
    status: string;
    planned_start_ms?: number | null;
    planned_end_ms?: number | null;
    attempt_count: number;
    max_attempts: number;
  };
}>();

const statusPercent = computed(() => {
  if (props.unit.status === "success") return 100;
  if (props.unit.status === "running") return 55;
  if (props.unit.status === "failed") return 100;
  return 10;
});

const statusType = computed<"default" | "success" | "warning" | "error" | "info">(() => {
  if (props.unit.status === "success") return "success";
  if (props.unit.status === "failed") return "error";
  if (props.unit.status === "running" || props.unit.status === "queued") return "warning";
  if (props.unit.status === "blocked") return "info";
  return "default";
});

const emit = defineEmits<{
  (event: "run", unitId: string): void;
  (event: "retry", unitId: string): void;
  (event: "patch", unitId: string): void;
  (event: "preview", unitId: string): void;
}>();
</script>

<style scoped>
.unit-card {
  background: #111827;
  border: 1px solid #1f2937;
}
.dialogue-card {
  border-left: 4px solid #8b5cf6;
}
</style>
