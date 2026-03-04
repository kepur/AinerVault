<template>
  <div class="page-grid production-page">
    <ProductionContextBar
      :loading="store.isLoading"
      :running="store.isRunning"
      :run-id="store.runId"
      :novel-id="store.context.novelId"
      :chapter-id="store.context.chapterId"
      :script-version="store.context.scriptVersion"
      :plan-version="store.context.planVersion"
      :persona-pack-id="store.context.personaPackId"
      :quality="store.context.quality"
      :selected-tracks="store.context.selectedTracks"
      :novel-options="store.novelSelectOptions"
      :chapter-options="store.chapterSelectOptions"
      :script-version-options="store.scriptVersionOptions"
      :plan-version-options="store.planVersionOptions"
      :persona-options="store.personaSelectOptions"
      :quality-options="store.qualityOptions"
      :track-options="store.trackOptions"
      @update:novel-id="onNovelChange"
      @update:chapter-id="onChapterChange"
      @update:script-version="(v) => (store.context.scriptVersion = v)"
      @update:plan-version="(v) => (store.context.planVersion = v)"
      @update:persona-pack-id="(v) => (store.context.personaPackId = v)"
      @update:quality="(v) => (store.context.quality = v)"
      @update:selected-tracks="onSelectedTracksChange"
      @use-track-preset="onUseTrackPreset"
      @create-run="onCreateRun"
      @init-tracks="onInitTracks"
      @run-selected="onRunSelectedTracks"
      @refresh="store.refreshTrackDashboard"
    />

    <ProductionRunStatusBar :run-meta="store.runMeta" :timeline-plan-loaded="store.timelinePlanLoaded" />

    <NGrid :cols="2" :x-gap="12" :y-gap="12" responsive="screen" item-responsive>
      <NGridItem span="0:2 1200:1">
        <ProductionTrackSummaryBar :items="store.trackSummaries" />
        <ProductionTrackBoard
          :active-track="store.activeTrack"
          :track-types="renderTrackTypes"
          :summaries="store.trackSummaries"
          :units-by-track="store.unitsByTrack"
          @update:active-track="(track) => (store.activeTrack = track)"
          @run-track="store.runTrack"
          @retry-failed="store.retryFailedInTrack"
          @open-settings="onOpenTrackSettings"
          @run-unit="store.runUnit"
          @retry-unit="onRetryUnit"
          @patch-unit="onPatchUnit"
          @preview-unit="onPreviewUnit"
        />
      </NGridItem>
      <NGridItem span="0:2 1200:1">
        <ProductionTimeDistributionPanel
          :run-id="store.runId"
          :blocks="store.timelineBlocks"
          @focus-unit="onFocusUnit"
          @assemble="onAssembleTimeline"
          @open-nle="onOpenNle"
        />
      </NGridItem>
    </NGrid>

    <NAlert v-if="store.message" type="success">{{ store.message }}</NAlert>
    <NAlert v-if="store.errorMessage" type="error">{{ store.errorMessage }}</NAlert>

    <ProductionRetryPatchDialog
      :show="retryDialogShow"
      :track-type="pendingPatchTrack || store.activeTrack"
      @update:show="(v) => (retryDialogShow = v)"
      @confirm="onConfirmPatch"
    />

    <ProductionTrackSettingsDrawer
      :show="trackSettingsShow"
      :track-type="trackSettingsTrackType"
      :max-inflight="trackMaxInflight"
      :auto-retry="trackAutoRetry"
      @update:show="(v) => (trackSettingsShow = v)"
      @update:max-inflight="(v) => (trackMaxInflight = v)"
      @update:auto-retry="(v) => (trackAutoRetry = v)"
    />

    <ProductionCandidateDrawer
      :show="candidateDrawerShow"
      :items="candidateItems"
      @update:show="(v) => (candidateDrawerShow = v)"
      @select="onSelectCandidate"
    />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { NAlert, NGrid, NGridItem } from "naive-ui";

import ProductionCandidateDrawer from "@/components/production/ProductionCandidateDrawer.vue";
import ProductionContextBar from "@/components/production/ProductionContextBar.vue";
import ProductionRetryPatchDialog from "@/components/production/ProductionRetryPatchDialog.vue";
import ProductionRunStatusBar from "@/components/production/ProductionRunStatusBar.vue";
import ProductionTimeDistributionPanel from "@/components/production/ProductionTimeDistributionPanel.vue";
import ProductionTrackBoard from "@/components/production/ProductionTrackBoard.vue";
import ProductionTrackSettingsDrawer from "@/components/production/ProductionTrackSettingsDrawer.vue";
import ProductionTrackSummaryBar from "@/components/production/ProductionTrackSummaryBar.vue";
import { useProductionBoardStore } from "@/stores/useProductionBoardStore";
import type { ProductionTrackType, RetryPatchPayload } from "@/types/production";

const router = useRouter();
const store = useProductionBoardStore();

const retryDialogShow = ref(false);
const pendingPatchTrack = ref<ProductionTrackType | null>(null);
const pendingPatchUnit = ref("");

const trackSettingsShow = ref(false);
const trackSettingsTrackType = ref<ProductionTrackType>("tts");
const trackMaxInflight = ref(4);
const trackAutoRetry = ref(true);

const candidateDrawerShow = ref(false);
const candidateItems = ref<Array<{ id: string; label: string; subtitle?: string; selected?: boolean }>>([]);
const pendingCandidateTrack = ref<ProductionTrackType | null>(null);
const pendingCandidateUnit = ref("");

const renderTrackTypes = computed<ProductionTrackType[]>(() => {
  const fromSummary = store.trackSummaries
    .map((item) => item.track_type)
    .filter((v): v is ProductionTrackType =>
      ["video", "storyboard", "lipsync", "tts", "dialogue", "narration", "sfx", "ambience", "aux", "bgm", "subtitle"].includes(v),
    );
  if (fromSummary.length > 0) {
    return Array.from(new Set(fromSummary));
  }
  return store.context.selectedTracks;
});

onMounted(async () => {
  await store.bootstrap();
});

async function onNovelChange(novelId: string): Promise<void> {
  await store.loadNovelContext(novelId);
}

async function onChapterChange(chapterId: string): Promise<void> {
  await store.loadChapterContext(chapterId);
}

function onSelectedTracksChange(values: string[]): void {
  store.context.selectedTracks = values.filter((v): v is ProductionTrackType =>
    ["video", "storyboard", "lipsync", "tts", "dialogue", "narration", "sfx", "ambience", "aux", "bgm", "subtitle"].includes(v),
  );
}

function onUseTrackPreset(preset: "audio" | "visual" | "all"): void {
  if (preset === "audio") {
    store.context.selectedTracks = ["dialogue", "narration", "sfx", "ambience", "aux", "bgm"];
    return;
  }
  if (preset === "visual") {
    store.context.selectedTracks = ["storyboard", "video", "lipsync", "subtitle"];
    return;
  }
  store.context.selectedTracks = [
    "storyboard",
    "video",
    "lipsync",
    "tts",
    "dialogue",
    "narration",
    "sfx",
    "ambience",
    "aux",
    "bgm",
    "subtitle",
  ];
}

async function onCreateRun(): Promise<void> {
  await store.createRun();
  if (store.runId) {
    await store.initTracks(false);
  }
}

async function onInitTracks(recreate: boolean): Promise<void> {
  await store.initTracks(recreate);
}

async function onRunSelectedTracks(): Promise<void> {
  await store.runSelectedTracks();
}

async function onRetryUnit(trackType: ProductionTrackType, unitId: string): Promise<void> {
  await store.retryUnit(trackType, unitId);
}

function onPatchUnit(trackType: ProductionTrackType, unitId: string): void {
  pendingPatchTrack.value = trackType;
  pendingPatchUnit.value = unitId;
  retryDialogShow.value = true;
}

async function onConfirmPatch(patch: RetryPatchPayload): Promise<void> {
  if (!pendingPatchTrack.value || !pendingPatchUnit.value) {
    return;
  }
  await store.retryUnit(pendingPatchTrack.value, pendingPatchUnit.value, patch);
}

async function onPreviewUnit(trackType: ProductionTrackType, unitId: string): Promise<void> {
  const unit = (store.unitsByTrack[trackType] || []).find((item) => item.unit_id === unitId);
  pendingCandidateTrack.value = trackType;
  pendingCandidateUnit.value = unitId;
  await store.loadAttemptHistory(unitId);

  const source = Array.isArray(unit?.output_candidates) ? unit.output_candidates : [];
  candidateItems.value = source.reduce<Array<{ id: string; label: string; subtitle?: string; selected?: boolean }>>(
    (acc, candidate, index) => {
      const artifactId = String(candidate.artifact_id || "");
      if (!artifactId) {
        return acc;
      }
      const jobId = String(candidate.job_id || "");
      const generatedAt = String(candidate.at || "");
      const uri = String(candidate.artifact_uri || candidate.origin_artifact_uri || "");
      acc.push({
        id: artifactId,
        label: `#${index + 1} ${artifactId}`,
        subtitle: [jobId ? `job:${jobId}` : "", generatedAt ? `at:${generatedAt}` : "", uri ? uri : ""]
          .filter(Boolean)
          .join(" | "),
        selected: artifactId === unit?.selected_asset_id,
      });
      return acc;
    },
    [],
  );

  if (candidateItems.value.length === 0 && unit?.selected_asset_id) {
    candidateItems.value = [
      {
        id: unit.selected_asset_id,
        label: `Selected ${unit.selected_asset_id}`,
        selected: true,
      },
    ];
  }
  candidateDrawerShow.value = true;
}

function onOpenTrackSettings(trackType: ProductionTrackType): void {
  trackSettingsTrackType.value = trackType;
  trackSettingsShow.value = true;
}

function onFocusUnit(trackType: ProductionTrackType, unitId: string): void {
  store.activeTrack = trackType;
  void onPreviewUnit(trackType, unitId);
}

async function onAssembleTimeline(): Promise<void> {
  await store.refreshTrackDashboard();
  if (!store.timelinePlanLoaded) {
    store.errorMessage = "timeline not ready yet, generate at least one track first";
    return;
  }
  await router.push({ path: "/studio/timeline", query: { run_id: store.runId } });
}

async function onOpenNle(): Promise<void> {
  if (!store.runId) {
    store.errorMessage = "run_id is required";
    return;
  }
  await router.push({ path: "/studio/timeline", query: { run_id: store.runId } });
}

async function onSelectCandidate(candidateId: string): Promise<void> {
  if (!pendingCandidateTrack.value || !pendingCandidateUnit.value) {
    return;
  }
  await store.selectCandidate(pendingCandidateTrack.value, pendingCandidateUnit.value, candidateId);
  await onPreviewUnit(pendingCandidateTrack.value, pendingCandidateUnit.value);
}
</script>

<style scoped>
.production-page {
  background: linear-gradient(180deg, #0b1220 0%, #060b14 100%);
}
</style>
