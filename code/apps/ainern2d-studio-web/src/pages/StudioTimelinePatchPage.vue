<template>
  <div class="page-grid">
    <NCard title="SKILL 30 · 多轨拖拽时间线 + PR Patch">
      <NGrid :cols="3" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Tenant ID">
            <NInput v-model:value="tenantId" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Project ID">
            <NInput v-model:value="projectId" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Run ID">
            <NInput v-model:value="runId" placeholder="run_xxx" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NSpace>
        <NButton type="primary" @click="onLoadTimeline">加载时间线</NButton>
        <NButton type="warning" :disabled="!runId || timelineLanes.length === 0" @click="onSaveTimelineEdits">
          保存拖拽编辑
        </NButton>
      </NSpace>
    </NCard>

    <NCard title="多轨拖拽编辑器">
      <NText depth="3">拖拽 clip 到同轨或跨轨位置；右侧可精调 track/start/duration，保存后写回 `/runs/{run_id}/timeline`。</NText>
      <div class="timeline-editor-shell">
        <div class="timeline-lanes">
          <div
            v-for="lane in timelineLanes"
            :key="lane.id"
            class="timeline-lane-row"
          >
            <div class="timeline-lane-label">{{ lane.label }}</div>
            <div
              class="timeline-lane-canvas"
              :style="{ width: `${timelineWidthPx}px` }"
              @dragover.prevent
              @drop="onDropClip(lane.id, $event)"
            >
              <div
                v-for="clip in lane.clips"
                :key="clip.id"
                class="timeline-clip"
                :class="{ selected: isSelectedClip(lane.id, clip.id) }"
                :style="clipStyle(clip)"
                draggable="true"
                @dragstart="onDragStart(lane.id, clip.id, $event)"
                @click="onSelectClip(lane.id, clip.id)"
              >
                <div class="timeline-clip-title">{{ clip.shot_id || clip.id }}</div>
                <div class="timeline-clip-meta">{{ clip.duration_ms }}ms</div>
              </div>
            </div>
          </div>
        </div>

        <div class="timeline-editor-panel">
          <NFormItem label="Selected Clip">
            <NInput :value="selectedClipLabel" readonly />
          </NFormItem>
          <NFormItem label="Track">
            <NSelect v-model:value="editTrackId" :options="laneOptions" :disabled="!hasSelectedClip" />
          </NFormItem>
          <NFormItem label="Start (ms)">
            <NInputNumber
              v-model:value="editStartMs"
              :min="0"
              :max="timelineDurationMs"
              style="width: 100%"
              :disabled="!hasSelectedClip"
            />
          </NFormItem>
          <NFormItem label="Duration (ms)">
            <NInputNumber
              v-model:value="editDurationMs"
              :min="100"
              style="width: 100%"
              :disabled="!hasSelectedClip"
            />
          </NFormItem>
          <NSpace>
            <NButton :disabled="!hasSelectedClip" @click="onApplyClipEdits">应用到 Clip</NButton>
          </NSpace>
        </div>
      </div>
    </NCard>

    <NCard title="Prompt Track (PR Patch)">
      <NDataTable :columns="promptColumns" :data="promptTrackItems" :pagination="{ pageSize: 8 }" />
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 900:1">
          <NFormItem label="Original Prompt">
            <NInput :value="originalPromptText" type="textarea" :autosize="{ minRows: 6, maxRows: 12 }" readonly />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 900:1">
          <NFormItem label="Edited Prompt">
            <NInput v-model:value="modifiedPromptText" type="textarea" :autosize="{ minRows: 6, maxRows: 12 }" />
          </NFormItem>
        </NGridItem>
      </NGrid>

      <NFormItem label="Patch Text（提交到 rerun-shot）">
        <NInput v-model:value="patchText" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" />
      </NFormItem>

      <NText depth="3">Diff Preview（PR Style）</NText>
      <div class="diff-panel">
        <div v-for="(line, idx) in diffLines" :key="idx" :class="['diff-line', `diff-${line.kind}`]">
          <span class="diff-prefix">{{ line.kind === "add" ? "+" : line.kind === "remove" ? "-" : " " }}</span>
          <span>{{ line.text }}</span>
        </div>
      </div>

      <NSpace>
        <NButton type="warning" :disabled="!shotId || !runId" @click="onPatchTimeline">Patch + Rerun Shot</NButton>
      </NSpace>
      <pre class="json-panel">{{ patchResultText }}</pre>
      <pre class="json-panel">{{ timelineText }}</pre>
    </NCard>

    <NAlert v-if="message" type="success" :show-icon="true">{{ message }}</NAlert>
    <NAlert v-if="errorMessage" type="error" :show-icon="true">{{ errorMessage }}</NAlert>
  </div>
</template>

<script setup lang="ts">
import { computed, h, ref } from "vue";
import {
  NAlert,
  NButton,
  NCard,
  NDataTable,
  NFormItem,
  NGrid,
  NGridItem,
  NInput,
  NInputNumber,
  NSelect,
  NSpace,
  NText,
  type DataTableColumns,
} from "naive-ui";

import {
  getRunTimeline,
  patchRunTimeline,
  type TimelinePlan,
  updateRunTimeline,
} from "@/api/product";

interface PromptTrackItem {
  plan_id?: string;
  shot_id: string;
  prompt_text: string;
  negative_prompt_text?: string | null;
}

interface DiffLine {
  kind: "context" | "add" | "remove";
  text: string;
}

interface TimelineLaneClip {
  id: string;
  shot_id: string;
  scene_id: string;
  start_ms: number;
  duration_ms: number;
  artifact_uri?: string | null;
}

interface TimelineLane {
  id: string;
  label: string;
  kind: "video" | "audio";
  role: string;
  clips: TimelineLaneClip[];
}

const tenantId = ref("default");
const projectId = ref("default");
const runId = ref("");
const shotId = ref("");

const promptTrackItems = ref<PromptTrackItem[]>([]);
const originalPromptText = ref("");
const modifiedPromptText = ref("");
const patchText = ref("");

const timelineText = ref("{}");
const patchResultText = ref("{}");
const message = ref("");
const errorMessage = ref("");

const timelineDurationMs = ref(60000);
const timelineWidthPx = ref(1200);
const timelineLanes = ref<TimelineLane[]>([]);
const effectTracks = ref<Array<Record<string, unknown>>>([]);

const selectedLaneId = ref("");
const selectedClipId = ref("");
const editTrackId = ref("");
const editStartMs = ref<number | null>(null);
const editDurationMs = ref<number | null>(null);

const promptColumns: DataTableColumns<PromptTrackItem> = [
  { title: "Shot", key: "shot_id" },
  {
    title: "Prompt",
    key: "prompt_text",
    render: (row) => h("span", { style: "font-size: 12px;" }, row.prompt_text.slice(0, 90)),
  },
  {
    title: "Action",
    key: "action",
    render: (row) =>
      h(NButton, { size: "small", type: "info", onClick: () => openPatchEditor(row) }, { default: () => "Edit" }),
  },
];

const diffLines = computed<DiffLine[]>(() => buildDiffLines(originalPromptText.value, modifiedPromptText.value));
const laneOptions = computed(() =>
  timelineLanes.value.map((lane) => ({ label: lane.label, value: lane.id }))
);

const selectedClip = computed(() => {
  const lane = timelineLanes.value.find((item) => item.id === selectedLaneId.value);
  if (!lane) {
    return null;
  }
  const clip = lane.clips.find((item) => item.id === selectedClipId.value);
  if (!clip) {
    return null;
  }
  return { lane, clip };
});

const hasSelectedClip = computed(() => Boolean(selectedClip.value));
const selectedClipLabel = computed(() => {
  if (!selectedClip.value) {
    return "";
  }
  return `${selectedClip.value.lane.label} / ${selectedClip.value.clip.shot_id || selectedClip.value.clip.id}`;
});

function stringifyError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function clearNotice(): void {
  message.value = "";
  errorMessage.value = "";
}

function toPrettyJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function clipStyle(clip: TimelineLaneClip): Record<string, string> {
  const left = Math.max(0, Math.round((clip.start_ms / Math.max(1, timelineDurationMs.value)) * timelineWidthPx.value));
  const width = Math.max(36, Math.round((clip.duration_ms / Math.max(1, timelineDurationMs.value)) * timelineWidthPx.value));
  return {
    left: `${left}px`,
    width: `${width}px`,
  };
}

function isSelectedClip(laneId: string, clipId: string): boolean {
  return selectedLaneId.value === laneId && selectedClipId.value === clipId;
}

function onSelectClip(laneId: string, clipId: string): void {
  selectedLaneId.value = laneId;
  selectedClipId.value = clipId;
  const lane = timelineLanes.value.find((item) => item.id === laneId);
  const clip = lane?.clips.find((item) => item.id === clipId);
  if (!lane || !clip) {
    return;
  }
  editTrackId.value = lane.id;
  editStartMs.value = clip.start_ms;
  editDurationMs.value = clip.duration_ms;
}

function onDragStart(laneId: string, clipId: string, event: DragEvent): void {
  if (!event.dataTransfer) {
    return;
  }
  event.dataTransfer.setData("application/json", JSON.stringify({ laneId, clipId }));
}

function onDropClip(targetLaneId: string, event: DragEvent): void {
  const transfer = event.dataTransfer?.getData("application/json");
  if (!transfer) {
    return;
  }
  const parsed = JSON.parse(transfer) as { laneId: string; clipId: string };
  const sourceLane = timelineLanes.value.find((lane) => lane.id === parsed.laneId);
  const targetLane = timelineLanes.value.find((lane) => lane.id === targetLaneId);
  if (!sourceLane || !targetLane) {
    return;
  }
  const clipIndex = sourceLane.clips.findIndex((clip) => clip.id === parsed.clipId);
  if (clipIndex < 0) {
    return;
  }
  const [clip] = sourceLane.clips.splice(clipIndex, 1);
  const canvas = event.currentTarget as HTMLElement;
  const rect = canvas.getBoundingClientRect();
  const ratio = Math.max(0, Math.min(1, (event.clientX - rect.left) / Math.max(1, rect.width)));
  const newStart = Math.round(ratio * timelineDurationMs.value);
  clip.start_ms = Math.max(0, Math.min(newStart, timelineDurationMs.value - clip.duration_ms));
  targetLane.clips.push(clip);
  targetLane.clips.sort((a, b) => a.start_ms - b.start_ms);
  onSelectClip(targetLane.id, clip.id);
}

function onApplyClipEdits(): void {
  if (!selectedClip.value || editStartMs.value === null || editDurationMs.value === null) {
    return;
  }
  const targetLane = timelineLanes.value.find((lane) => lane.id === editTrackId.value);
  if (!targetLane) {
    return;
  }
  const { lane, clip } = selectedClip.value;
  const clipRef = lane.clips.find((item) => item.id === clip.id);
  if (!clipRef) {
    return;
  }
  clipRef.start_ms = Math.max(0, editStartMs.value);
  clipRef.duration_ms = Math.max(100, editDurationMs.value);
  if (lane.id !== targetLane.id) {
    lane.clips = lane.clips.filter((item) => item.id !== clip.id);
    targetLane.clips.push(clipRef);
    selectedLaneId.value = targetLane.id;
  }
  targetLane.clips.sort((a, b) => a.start_ms - b.start_ms);
  normalizeTimelineDuration();
}

function normalizeTimelineDuration(): void {
  let maxEnd = 0;
  for (const lane of timelineLanes.value) {
    for (const clip of lane.clips) {
      maxEnd = Math.max(maxEnd, clip.start_ms + clip.duration_ms);
    }
  }
  timelineDurationMs.value = Math.max(5000, maxEnd);
}

function buildDiffLines(beforeText: string, afterText: string): DiffLine[] {
  const before = beforeText.split("\n");
  const after = afterText.split("\n");
  const result: DiffLine[] = [];
  let i = 0;
  let j = 0;

  while (i < before.length || j < after.length) {
    const b = before[i];
    const a = after[j];
    if (b === a) {
      if (b !== undefined) {
        result.push({ kind: "context", text: b });
      }
      i += 1;
      j += 1;
      continue;
    }
    if (a !== undefined && before[i] === after[j + 1]) {
      result.push({ kind: "add", text: a });
      j += 1;
      continue;
    }
    if (b !== undefined && before[i + 1] === after[j]) {
      result.push({ kind: "remove", text: b });
      i += 1;
      continue;
    }
    if (b !== undefined) {
      result.push({ kind: "remove", text: b });
    }
    if (a !== undefined) {
      result.push({ kind: "add", text: a });
    }
    i += 1;
    j += 1;
  }

  return result;
}

function openPatchEditor(item: PromptTrackItem): void {
  shotId.value = item.shot_id;
  originalPromptText.value = item.prompt_text || "";
  modifiedPromptText.value = item.prompt_text || "";
  patchText.value = item.prompt_text || "";
}

function parseTimelineLanes(timeline: TimelinePlan): void {
  const videoItems = timeline.video_tracks as Array<Record<string, unknown>>;
  const audioItems = timeline.audio_tracks as Array<Record<string, unknown>>;
  const lanes: TimelineLane[] = [];
  lanes.push({
    id: "video",
    label: "Video Track",
    kind: "video",
    role: "video",
    clips: videoItems.map((item) => ({
      id: String(item.id || ""),
      shot_id: String(item.shot_id || ""),
      scene_id: String(item.scene_id || ""),
      start_ms: Number(item.start_time_ms || 0),
      duration_ms: Number(item.duration_ms || 0),
      artifact_uri: item.artifact_uri ? String(item.artifact_uri) : null,
    })),
  });

  const audioByRole = new Map<string, TimelineLaneClip[]>();
  for (const item of audioItems) {
    const role = String(item.role || "audio");
    if (!audioByRole.has(role)) {
      audioByRole.set(role, []);
    }
    audioByRole.get(role)?.push({
      id: String(item.id || ""),
      shot_id: "",
      scene_id: "",
      start_ms: Number(item.start_time_ms || 0),
      duration_ms: Number(item.duration_ms || 0),
      artifact_uri: item.artifact_uri ? String(item.artifact_uri) : null,
    });
  }
  for (const [role, clips] of audioByRole.entries()) {
    lanes.push({
      id: role,
      label: `Audio · ${role}`,
      kind: "audio",
      role,
      clips: clips.sort((a, b) => a.start_ms - b.start_ms),
    });
  }

  timelineLanes.value = lanes;
  timelineDurationMs.value = Math.max(5000, timeline.total_duration_ms || 0);
  normalizeTimelineDuration();
}

function buildTimelinePayload(): TimelinePlan {
  const payload: TimelinePlan = {
    run_id: runId.value,
    total_duration_ms: timelineDurationMs.value,
    video_tracks: [],
    audio_tracks: [],
    effect_tracks: effectTracks.value,
  };

  for (const lane of timelineLanes.value) {
    for (const clip of lane.clips) {
      if (lane.kind === "video") {
        payload.video_tracks.push({
          id: clip.id,
          shot_id: clip.shot_id,
          scene_id: clip.scene_id || "",
          start_time_ms: clip.start_ms,
          duration_ms: clip.duration_ms,
          artifact_uri: clip.artifact_uri || undefined,
        });
      } else {
        payload.audio_tracks.push({
          id: clip.id,
          role: lane.role,
          start_time_ms: clip.start_ms,
          duration_ms: clip.duration_ms,
          artifact_uri: clip.artifact_uri || undefined,
          text_content: null,
          volume: 1.0,
        });
      }
    }
  }
  return payload;
}

async function onLoadTimeline(): Promise<void> {
  clearNotice();
  if (!runId.value) {
    errorMessage.value = "run_id is required";
    return;
  }
  try {
    const timeline = await getRunTimeline(runId.value);
    timelineText.value = toPrettyJson(timeline);
    effectTracks.value = Array.isArray(timeline.effect_tracks) ? timeline.effect_tracks : [];
    parseTimelineLanes(timeline);

    const promptTrack = effectTracks.value.find((track) => track.track === "prompt");
    const items = Array.isArray(promptTrack?.items) ? promptTrack.items : [];
    promptTrackItems.value = items.map((item) => ({
      plan_id: String(item.plan_id || ""),
      shot_id: String(item.shot_id || ""),
      prompt_text: String(item.prompt_text || ""),
      negative_prompt_text: item.negative_prompt_text ? String(item.negative_prompt_text) : null,
    }));
    if (promptTrackItems.value.length > 0) {
      openPatchEditor(promptTrackItems.value[0]);
    }
  } catch (error) {
    errorMessage.value = `load timeline failed: ${stringifyError(error)}`;
  }
}

async function onSaveTimelineEdits(): Promise<void> {
  clearNotice();
  if (!runId.value) {
    errorMessage.value = "run_id is required";
    return;
  }
  try {
    const payload = buildTimelinePayload();
    const updated = await updateRunTimeline(runId.value, payload);
    timelineText.value = toPrettyJson(updated);
    message.value = "timeline drag edits saved";
  } catch (error) {
    errorMessage.value = `save timeline failed: ${stringifyError(error)}`;
  }
}

async function onPatchTimeline(): Promise<void> {
  clearNotice();
  if (!runId.value || !shotId.value) {
    errorMessage.value = "run_id and shot_id are required";
    return;
  }
  try {
    const payload = modifiedPromptText.value.trim() || patchText.value;
    const result = await patchRunTimeline(runId.value, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      shot_id: shotId.value,
      patch_text: payload,
      track: "prompt",
      patch_scope: "rerun-shot",
      requested_by: "studio-web",
    });
    patchResultText.value = toPrettyJson(result);
    message.value = `patch queued: ${result.job_id}`;
  } catch (error) {
    errorMessage.value = `patch failed: ${stringifyError(error)}`;
  }
}
</script>
