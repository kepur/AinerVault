<template>
  <NCard title="Run Status">
    <NSpace>
      <NTag type="default" :bordered="false">Run: {{ runMeta.runId || '(none)' }}</NTag>
      <NTag type="info" :bordered="false">Status: {{ runMeta.status }}</NTag>
      <NTag type="warning" :bordered="false">Stage: {{ runMeta.stage }}</NTag>
      <NTag type="success" :bordered="false">Progress: {{ runMeta.progress }}%</NTag>
      <NTag type="default" :bordered="false">Timeline: {{ timelinePlanLoaded ? 'ready' : 'not assembled' }}</NTag>
    </NSpace>
  </NCard>
</template>

<script setup lang="ts">
import { NCard, NSpace, NTag } from "naive-ui";

defineProps<{
  runMeta: {
    runId: string;
    status: string;
    stage: string;
    progress: number;
  };
  timelinePlanLoaded: boolean;
}>();
</script>
