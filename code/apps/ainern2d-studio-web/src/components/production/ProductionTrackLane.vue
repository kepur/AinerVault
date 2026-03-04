<template>
  <NCard :title="title" class="track-lane" size="small">
    <template #header-extra>
      <NSpace>
        <NButton size="small" type="primary" @click="emit('run-track', trackType)">Run All</NButton>
        <NButton size="small" @click="emit('retry-failed', trackType)">Retry Failed</NButton>
        <NButton size="small" @click="emit('open-settings', trackType)">Settings</NButton>
      </NSpace>
    </template>

    <NEmpty v-if="!units.length" description="No units" />
    <div v-else class="unit-grid">
      <component
        :is="unitComponent(unit)"
        v-for="unit in units"
        :key="unit.unit_id"
        :unit="unit"
        @run="(unitId: string) => emit('run-unit', trackType, unitId)"
        @retry="(unitId: string) => emit('retry-unit', trackType, unitId)"
        @patch="(unitId: string) => emit('patch-unit', trackType, unitId)"
        @preview="(unitId: string) => emit('preview-unit', trackType, unitId)"
      />
    </div>
  </NCard>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { NButton, NCard, NEmpty, NSpace } from "naive-ui";

import ProductionUnitCardDialogue from "@/components/production/ProductionUnitCardDialogue.vue";
import ProductionUnitCardEvent from "@/components/production/ProductionUnitCardEvent.vue";
import ProductionUnitCardShot from "@/components/production/ProductionUnitCardShot.vue";
import type { ProductionTrackType } from "@/types/production";

const props = defineProps<{
  trackType: ProductionTrackType;
  summary?: {
    status: string;
    total_units: number;
    success_units: number;
    failed_units: number;
    running_units: number;
  };
  units: Array<{
    unit_id: string;
    unit_ref_id: string;
    unit_kind: string;
    status: string;
    planned_start_ms?: number | null;
    planned_end_ms?: number | null;
    attempt_count: number;
    max_attempts: number;
    last_error_message?: string | null;
  }>;
}>();

const emit = defineEmits<{
  (event: "run-track", trackType: ProductionTrackType): void;
  (event: "retry-failed", trackType: ProductionTrackType): void;
  (event: "open-settings", trackType: ProductionTrackType): void;
  (event: "run-unit", trackType: ProductionTrackType, unitId: string): void;
  (event: "retry-unit", trackType: ProductionTrackType, unitId: string): void;
  (event: "patch-unit", trackType: ProductionTrackType, unitId: string): void;
  (event: "preview-unit", trackType: ProductionTrackType, unitId: string): void;
}>();

const title = computed(() => {
  const label = trackLabel(props.trackType);
  const summaryText = props.summary
    ? `(${props.summary.success_units}/${props.summary.total_units}, failed:${props.summary.failed_units}, running:${props.summary.running_units})`
    : "";
  return `${label} ${summaryText}`;
});

function unitComponent(unit: { unit_kind: string; }): unknown {
  if (unit.unit_kind === "dialogue" || unit.unit_kind === "subtitle_line") return ProductionUnitCardDialogue;
  if (unit.unit_kind === "event" || unit.unit_kind === "segment") return ProductionUnitCardEvent;
  return ProductionUnitCardShot;
}

function trackLabel(trackType: ProductionTrackType): string {
  const labels: Record<ProductionTrackType, string> = {
    storyboard: "Storyboard Track",
    video: "Video Track",
    lipsync: "LipSync Track",
    tts: "TTS Track",
    dialogue: "Dialogue Track",
    narration: "Narration Track",
    sfx: "SFX Track",
    ambience: "Ambience Track",
    aux: "AUX Track",
    bgm: "BGM Track",
    subtitle: "Subtitle Track",
  };
  return labels[trackType] || trackType;
}
</script>

<style scoped>
.track-lane {
  background: #0b1220;
  border: 1px solid #1f2937;
}
.unit-grid {
  display: grid;
  gap: 8px;
  grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
}
</style>
