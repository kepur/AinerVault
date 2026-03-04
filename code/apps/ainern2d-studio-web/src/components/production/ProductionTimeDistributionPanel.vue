<template>
  <NCard title="Time Distribution">
    <NSpace>
      <NButton type="primary" :disabled="!runId" @click="emit('assemble')">Assemble Timeline</NButton>
      <NButton :disabled="!runId" @click="emit('open-nle')">Open NLE</NButton>
    </NSpace>

    <div class="timeline-shell" v-if="blocks.length">
      <div class="timeline-ruler">
        <span>0s</span>
        <span>{{ Math.round(totalDurationMs / 1000) }}s</span>
      </div>
      <div class="timeline-track" v-for="trackType in trackOrder" :key="trackType">
        <div class="track-label">{{ trackType.toUpperCase() }}</div>
        <div class="track-canvas">
          <div
            v-for="block in trackBlocks(trackType)"
            :key="block.unitId"
            class="timeline-block"
            :class="[`track-${block.trackType}`, `status-${block.status}`]"
            :style="blockStyle(block)"
            @click="emit('focus-unit', block.trackType, block.unitId)"
          >
            {{ block.label }}
          </div>
        </div>
      </div>
    </div>
    <NEmpty v-else description="No planned units yet" />
  </NCard>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { NButton, NCard, NEmpty, NSpace } from "naive-ui";
import type { ProductionTimelineBlock, ProductionTrackType } from "@/types/production";

const props = defineProps<{
  runId: string;
  blocks: ProductionTimelineBlock[];
}>();

const emit = defineEmits<{
  (event: "focus-unit", trackType: ProductionTrackType, unitId: string): void;
  (event: "assemble"): void;
  (event: "open-nle"): void;
}>();

const trackOrder: ProductionTrackType[] = [
  "storyboard",
  "video",
  "lipsync",
  "dialogue",
  "narration",
  "tts",
  "sfx",
  "ambience",
  "aux",
  "bgm",
  "subtitle",
];

const totalDurationMs = computed(() => {
  if (!props.blocks.length) return 1000;
  return props.blocks.reduce((acc, item) => Math.max(acc, item.endMs), 1000);
});

function trackBlocks(trackType: ProductionTrackType): ProductionTimelineBlock[] {
  return props.blocks.filter((item) => item.trackType === trackType);
}

function blockStyle(block: ProductionTimelineBlock): Record<string, string> {
  const duration = Math.max(1, totalDurationMs.value);
  const left = Math.round((block.startMs / duration) * 1000) / 10;
  const width = Math.max(5, Math.round(((block.endMs - block.startMs) / duration) * 1000) / 10);
  return {
    left: `${left}%`,
    width: `${width}%`,
  };
}
</script>

<style scoped>
.timeline-shell {
  margin-top: 12px;
  display: grid;
  gap: 10px;
}
.timeline-ruler {
  display: flex;
  justify-content: space-between;
  color: #9ca3af;
  font-size: 12px;
}
.timeline-track {
  display: grid;
  grid-template-columns: 90px 1fr;
  gap: 8px;
  align-items: center;
}
.track-label {
  color: #d1d5db;
  font-size: 12px;
}
.track-canvas {
  position: relative;
  height: 30px;
  border: 1px solid #374151;
  background: #111827;
  border-radius: 6px;
  overflow: hidden;
}
.timeline-block {
  position: absolute;
  top: 3px;
  height: 24px;
  font-size: 11px;
  line-height: 24px;
  padding: 0 6px;
  border-radius: 4px;
  cursor: pointer;
  color: #f9fafb;
  white-space: nowrap;
  overflow: hidden;
}
.track-video { background: #2563eb; }
.track-tts { background: #7c3aed; }
.track-sfx { background: #d97706; }
.track-ambience { background: #0d9488; }
.track-aux { background: #0891b2; }
.track-bgm { background: #16a34a; }
.track-subtitle { background: #4b5563; }
.track-storyboard { background: #0ea5e9; }
.track-dialogue { background: #8b5cf6; }
.track-narration { background: #a855f7; }
.track-lipsync { background: #2563eb; }
.status-failed { outline: 2px solid #dc2626; }
.status-running { opacity: 0.8; }
</style>
