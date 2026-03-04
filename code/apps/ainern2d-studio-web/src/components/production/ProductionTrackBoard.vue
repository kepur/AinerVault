<template>
  <NCard title="Track Execution Board">
    <NTabs :value="activeTrack" type="line" @update:value="(v) => emit('update:activeTrack', v as ProductionTrackType)">
      <NTabPane v-for="trackType in trackTypes" :key="trackType" :name="trackType" :tab="trackLabel(trackType)">
        <ProductionTrackLane
          :track-type="trackType"
          :summary="summaryMap[trackType]"
          :units="unitsByTrack[trackType] || []"
          @run-track="(track) => emit('run-track', track)"
          @retry-failed="(track) => emit('retry-failed', track)"
          @open-settings="(track) => emit('open-settings', track)"
          @run-unit="(track, unitId) => emit('run-unit', track, unitId)"
          @retry-unit="(track, unitId) => emit('retry-unit', track, unitId)"
          @patch-unit="(track, unitId) => emit('patch-unit', track, unitId)"
          @preview-unit="(track, unitId) => emit('preview-unit', track, unitId)"
        />
      </NTabPane>
    </NTabs>
  </NCard>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { NCard, NTabPane, NTabs } from "naive-ui";

import ProductionTrackLane from "@/components/production/ProductionTrackLane.vue";
import type { ProductionTrackType } from "@/types/production";

const props = defineProps<{
  activeTrack: ProductionTrackType;
  trackTypes: ProductionTrackType[];
  summaries: Array<{
    track_type: string;
    status: string;
    total_units: number;
    success_units: number;
    failed_units: number;
    running_units: number;
  }>;
  unitsByTrack: Record<string, Array<{
    unit_id: string;
    unit_ref_id: string;
    unit_kind: string;
    status: string;
    planned_start_ms?: number | null;
    planned_end_ms?: number | null;
    attempt_count: number;
    max_attempts: number;
    last_error_message?: string | null;
  }>>;
}>();

const emit = defineEmits<{
  (event: "update:activeTrack", trackType: ProductionTrackType): void;
  (event: "run-track", trackType: ProductionTrackType): void;
  (event: "retry-failed", trackType: ProductionTrackType): void;
  (event: "open-settings", trackType: ProductionTrackType): void;
  (event: "run-unit", trackType: ProductionTrackType, unitId: string): void;
  (event: "retry-unit", trackType: ProductionTrackType, unitId: string): void;
  (event: "patch-unit", trackType: ProductionTrackType, unitId: string): void;
  (event: "preview-unit", trackType: ProductionTrackType, unitId: string): void;
}>();

const summaryMap = computed(() => {
  const map: Record<string, (typeof props.summaries)[number]> = {};
  for (const item of props.summaries) {
    map[item.track_type] = item;
  }
  return map;
});

const TRACK_LABELS: Record<ProductionTrackType, string> = {
  storyboard: "Storyboard",
  video: "Video",
  lipsync: "LipSync",
  tts: "TTS",
  dialogue: "Dialogue",
  narration: "Narration",
  sfx: "SFX",
  ambience: "Ambience",
  aux: "AUX",
  bgm: "BGM",
  subtitle: "Subtitle",
};

function trackLabel(trackType: ProductionTrackType): string {
  return TRACK_LABELS[trackType] || trackType;
}
</script>
