<template>
  <div class="page-grid">
    <NCard title="SKILL 28 · Task / Run 运行中心（P0 可观测）">
      <NGrid :cols="4" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:4 900:1">
          <NFormItem label="Tenant ID">
            <NInput v-model:value="tenantId" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:4 900:1">
          <NFormItem label="Project ID">
            <NInput v-model:value="projectId" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:4 900:1">
          <NFormItem label="Chapter ID">
            <NInput v-model:value="chapterId" placeholder="chapter_xxx" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:4 900:1">
          <NFormItem label="Requested Quality">
            <NSelect v-model:value="requestedQuality" :options="qualityOptions" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NGrid :cols="3" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Language Context">
            <NInput v-model:value="languageContext" placeholder="en-US" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Culture Pack">
            <NInput v-model:value="culturePackId" placeholder="cn_wuxia" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Persona Ref">
            <NInput v-model:value="personaRef" placeholder="director_A@v1" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Track Mode">
            <NSwitch v-model:value="trackMode" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NSpace>
        <NButton type="primary" @click="onCreateTask">{{ t('runs.createRun') }}</NButton>
        <NButton @click="onLoadSnapshot" :disabled="!runId">{{ t('common.details') }}</NButton>
        <NButton type="info" @click="onLoadRunObservability" :disabled="!runId">{{ t('runs.loadObs') }}</NButton>
      </NSpace>
      <NSpace>
        <NTag type="success" :bordered="false">Run ID: {{ runId || "(none)" }}</NTag>
        <NTag v-if="runDetail" type="info" :bordered="false">Status: {{ runDetail.status }}</NTag>
        <NTag v-if="runDetail" type="warning" :bordered="false">Stage: {{ runDetail.stage }}</NTag>
        <NTag v-if="runDetail" type="default" :bordered="false">Progress: {{ runDetail.progress }}%</NTag>
      </NSpace>
      <pre class="json-panel">{{ snapshotText }}</pre>
    </NCard>

    <NCard title="Quick Pick Chapter">
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 900:1">
          <NFormItem label="Novel ID">
            <NInput v-model:value="selectedNovelId" placeholder="novel_xxx" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 900:1">
          <NFormItem label="Actions">
            <NSpace>
              <NButton @click="onListNovels">Novel 列表</NButton>
              <NButton @click="onListChapters">Chapter 列表</NButton>
            </NSpace>
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NDataTable :columns="novelColumns" :data="novels" :pagination="{ pageSize: 4 }" />
      <NDataTable :columns="chapterColumns" :data="chapters" :pagination="{ pageSize: 6 }" />
    </NCard>

    <NCard title="Run 详情 / Prompt 回放 / Policy 回放">
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 1200:1">
          <NText depth="3">Run Detail</NText>
          <pre class="json-panel">{{ runDetailText }}</pre>
        </NGridItem>
        <NGridItem span="0:2 1200:1">
          <NText depth="3">Latest Error</NText>
          <pre class="json-panel">{{ runErrorText }}</pre>
        </NGridItem>
      </NGrid>
      <NText depth="3">Prompt Plans</NText>
      <NDataTable :columns="promptColumns" :data="promptPlans" :pagination="{ pageSize: 6 }" />
      <NText depth="3">Policy Stacks</NText>
      <NDataTable :columns="policyColumns" :data="policyStacks" :pagination="{ pageSize: 6 }" />
    </NCard>

    <NCard title="分轨控制台（可单轨运行/重试）">
      <NText depth="3">分层建议：1) 初始化轨道 2) 先跑单轨（推荐 TTS）3) 对失败 Unit 做逐条重试</NText>
      <NGrid :cols="3" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:3 1200:2">
          <NFormItem label="Track Set">
            <NSelect v-model:value="selectedTracks" :options="trackOptions" multiple clearable />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:3 1200:1">
          <NFormItem label="Active Track">
            <NSelect v-model:value="activeTrackType" :options="trackOptions" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NSpace>
        <NButton type="primary" :disabled="!runId" @click="onInitTracks(false)">初始化轨道</NButton>
        <NButton :disabled="!runId" @click="onInitTracks(true)">重建轨道</NButton>
        <NButton type="info" :disabled="!runId || !activeTrackType" @click="onRunActiveTrack">运行当前轨道</NButton>
        <NButton :disabled="!runId || !activeTrackType" @click="onRetryFailedInActiveTrack">重试当前轨道失败项</NButton>
        <NButton :disabled="!runId" @click="onLoadTrackDashboard">刷新轨道看板</NButton>
      </NSpace>
      <NText depth="3">Track Summary</NText>
      <NDataTable :columns="trackColumns" :data="trackSummaries" :pagination="{ pageSize: 6 }" />
      <NText depth="3">Track Units · {{ activeTrackType || "N/A" }}</NText>
      <NDataTable :columns="unitColumns" :data="trackUnits" :pagination="{ pageSize: 8 }" />
    </NCard>

    <NAlert v-if="message" type="success" :show-icon="true">{{ message }}</NAlert>
    <NAlert v-if="errorMessage" type="error" :show-icon="true">{{ errorMessage }}</NAlert>
  </div>
</template>

<script setup lang="ts">
import { h, onMounted, ref, watch } from "vue";
import {
  NAlert,
  NButton,
  NCard,
  NDataTable,
  NFormItem,
  NGrid,
  NGridItem,
  NInput,
  NSelect,
  NSwitch,
  NSpace,
  NTag,
  NText,
  type DataTableColumns,
} from "naive-ui";
import { useI18n } from "@/composables/useI18n";


import {
  type ChapterResponse,
  type InitTracksResponse,
  type NovelResponse,
  type PolicyStackReplayItem,
  type PromptPlanReplayItem,
  type RunDetailResponse,
  type RunTrackResponse,
  type TrackSummary,
  type TrackUnitItem,
  createChapterTask,
  getRunDetail,
  getRunPolicyStacks,
  getRunPromptPlans,
  getRunSnapshot,
  initRunTracks,
  listChapters,
  listNovels,
  listRunTracks,
  listRunTrackUnits,
  retryTrackUnit,
  runTrack,
} from "@/api/product";

const { t } = useI18n();

const tenantId = ref("default");
const projectId = ref("default");
const chapterId = ref("");
const requestedQuality = ref("standard");
const languageContext = ref("en-US");
const culturePackId = ref("cn_wuxia");
const personaRef = ref("director_A@v1");
const trackMode = ref(true);

const runId = ref("");
const runDetail = ref<RunDetailResponse | null>(null);
const runDetailText = ref("{}");
const runErrorText = ref("{}");
const snapshotText = ref("{}");
const promptPlans = ref<PromptPlanReplayItem[]>([]);
const policyStacks = ref<PolicyStackReplayItem[]>([]);

const novels = ref<NovelResponse[]>([]);
const chapters = ref<ChapterResponse[]>([]);
const selectedNovelId = ref("");

const trackOptions = [
  { label: "视频 Video", value: "video" },
  { label: "配音 TTS", value: "tts" },
  { label: "音效 SFX", value: "sfx" },
  { label: "背景 BGM", value: "bgm" },
  { label: "字幕 Subtitle", value: "subtitle" },
  { label: "分镜 Storyboard", value: "storyboard" },
];
const selectedTracks = ref<string[]>(["video", "tts", "sfx", "bgm"]);
const activeTrackType = ref<string>("tts");
const trackSummaries = ref<TrackSummary[]>([]);
const trackUnits = ref<TrackUnitItem[]>([]);

const message = ref("");
const errorMessage = ref("");

const qualityOptions = [
  { label: "draft", value: "draft" },
  { label: "standard", value: "standard" },
  { label: "high", value: "high" },
];

const novelColumns: DataTableColumns<NovelResponse> = [
  { title: "ID", key: "id" },
  { title: "Title", key: "title" },
  {
    title: "Action",
    key: "action",
    render: (row) =>
      h(NButton, {
        size: "small",
        onClick: () => {
          selectedNovelId.value = row.id;
          void onListChapters();
        },
      }, { default: () => "Use" }),
  },
];

const chapterColumns: DataTableColumns<ChapterResponse> = [
  { title: "Chapter ID", key: "id" },
  { title: "No", key: "chapter_no" },
  { title: "Title", key: "title" },
  {
    title: "Action",
    key: "action",
    render: (row) =>
      h(NButton, {
        size: "small",
        type: "info",
        onClick: () => {
          chapterId.value = row.id;
        },
      }, { default: () => "Use" }),
  },
];

const promptColumns: DataTableColumns<PromptPlanReplayItem> = [
  { title: "Plan ID", key: "plan_id" },
  { title: "Shot", key: "shot_id" },
  {
    title: "Prompt",
    key: "prompt_text",
    render: (row) => (row.prompt_text.length > 120 ? `${row.prompt_text.slice(0, 120)}...` : row.prompt_text),
  },
];

const policyColumns: DataTableColumns<PolicyStackReplayItem> = [
  { title: "Policy Stack", key: "policy_stack_id" },
  { title: "Name", key: "name" },
  { title: "Status", key: "status" },
  { title: "Persona", key: "active_persona_ref" },
  {
    title: "Review Items",
    key: "review_items",
    render: (row) => row.review_items.join(","),
  },
  {
    title: "Summary",
    key: "summary",
    render: (row) => `hard:${row.hard_constraints} soft:${row.soft_constraints} conflict:${row.conflicts}`,
  },
];

function stringifyError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function toPrettyJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function clearNotice(): void {
  message.value = "";
  errorMessage.value = "";
}

function statusTagType(status: string): "default" | "success" | "warning" | "error" | "info" {
  if (status === "success" || status === "done") {
    return "success";
  }
  if (status === "failed") {
    return "error";
  }
  if (status === "running" || status === "queued") {
    return "warning";
  }
  if (status === "blocked" || status === "partial") {
    return "info";
  }
  return "default";
}

const trackColumns: DataTableColumns<TrackSummary> = [
  { title: "Track", key: "track_type" },
  { title: "Worker", key: "worker_type" },
  {
    title: "Status",
    key: "status",
    render: (row) => h(NTag, { type: statusTagType(row.status), bordered: false }, { default: () => row.status }),
  },
  {
    title: "Progress",
    key: "progress",
    render: (row) => `${row.success_units}/${row.total_units} (failed:${row.failed_units}, running:${row.running_units})`,
  },
  {
    title: "Blocked",
    key: "blocked_reason",
    render: (row) => row.blocked_reason || "-",
  },
];

const unitColumns: DataTableColumns<TrackUnitItem> = [
  { title: "Unit ID", key: "unit_id" },
  { title: "Ref", key: "unit_ref_id" },
  { title: "Kind", key: "unit_kind" },
  {
    title: "Planned(ms)",
    key: "planned",
    render: (row) => `${row.planned_start_ms ?? "-"} -> ${row.planned_end_ms ?? "-"}`,
  },
  {
    title: "Status",
    key: "status",
    render: (row) => h(NTag, { type: statusTagType(row.status), bordered: false }, { default: () => row.status }),
  },
  {
    title: "Attempts",
    key: "attempt_count",
    render: (row) => `${row.attempt_count}/${row.max_attempts}`,
  },
  {
    title: "Error",
    key: "error",
    render: (row) => row.last_error_message || row.last_error_code || "-",
  },
  {
    title: "Action",
    key: "action",
    render: (row) =>
      h(NButton, {
        size: "small",
        type: "warning",
        disabled: !runId.value,
        onClick: () => {
          void onRetryUnit(row);
        },
      }, { default: () => "Retry" }),
  },
];

async function onCreateTask(): Promise<void> {
  clearNotice();
  if (!chapterId.value) {
    errorMessage.value = "chapter_id is required";
    return;
  }
  try {
    const accepted = await createChapterTask(chapterId.value, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      requested_quality: requestedQuality.value,
      language_context: languageContext.value,
      payload: {
        source_language: languageContext.value,
        target_language: languageContext.value,
        culture_pack_id: culturePackId.value || undefined,
        persona_ref: personaRef.value || undefined,
        track_mode: trackMode.value,
      },
    });
    runId.value = accepted.run_id;
    message.value = `run created: ${accepted.run_id}`;
    await onLoadSnapshot();
    await onLoadRunObservability();
    if (trackMode.value) {
      await onLoadTrackDashboard();
    }
  } catch (error) {
    errorMessage.value = `create task failed: ${stringifyError(error)}`;
  }
}

async function onLoadSnapshot(): Promise<void> {
  clearNotice();
  if (!runId.value) {
    errorMessage.value = "run_id is required";
    return;
  }
  try {
    const snapshot = await getRunSnapshot(runId.value);
    snapshotText.value = toPrettyJson(snapshot);
  } catch (error) {
    errorMessage.value = `load snapshot failed: ${stringifyError(error)}`;
  }
}

async function onLoadRunObservability(): Promise<void> {
  clearNotice();
  if (!runId.value) {
    errorMessage.value = "run_id is required";
    return;
  }
  try {
    const [detail, prompts, policies] = await Promise.all([
      getRunDetail(runId.value),
      getRunPromptPlans(runId.value, { limit: 100, offset: 0 }),
      getRunPolicyStacks(runId.value),
    ]);
    runDetail.value = detail;
    runDetailText.value = toPrettyJson(detail);
    runErrorText.value = toPrettyJson(detail.latest_error || {});
    promptPlans.value = prompts;
    policyStacks.value = policies;
    message.value = "run observability loaded";
  } catch (error) {
    errorMessage.value = `load run observability failed: ${stringifyError(error)}`;
  }
}

async function onListNovels(): Promise<void> {
  clearNotice();
  try {
    novels.value = await listNovels(tenantId.value, projectId.value);
  } catch (error) {
    errorMessage.value = `list novels failed: ${stringifyError(error)}`;
  }
}

async function onListChapters(): Promise<void> {
  clearNotice();
  if (!selectedNovelId.value) {
    return;
  }
  try {
    chapters.value = await listChapters(selectedNovelId.value);
  } catch (error) {
    errorMessage.value = `list chapters failed: ${stringifyError(error)}`;
  }
}

async function loadActiveTrackUnits(): Promise<void> {
  if (!runId.value || !activeTrackType.value) {
    trackUnits.value = [];
    return;
  }
  try {
    trackUnits.value = await listRunTrackUnits(runId.value, activeTrackType.value);
  } catch (error) {
    trackUnits.value = [];
    errorMessage.value = `load track units failed: ${stringifyError(error)}`;
  }
}

async function onLoadTrackDashboard(): Promise<void> {
  clearNotice();
  if (!runId.value) {
    errorMessage.value = "run_id is required";
    return;
  }
  try {
    trackSummaries.value = await listRunTracks(runId.value);
    const available = new Set(trackSummaries.value.map((item) => item.track_type));
    if (activeTrackType.value && !available.has(activeTrackType.value) && trackSummaries.value.length > 0) {
      activeTrackType.value = trackSummaries.value[0].track_type;
    }
    await loadActiveTrackUnits();
    message.value = "track dashboard loaded";
  } catch (error) {
    errorMessage.value = `load track dashboard failed: ${stringifyError(error)}`;
  }
}

async function onInitTracks(recreate: boolean): Promise<void> {
  clearNotice();
  if (!runId.value) {
    errorMessage.value = "run_id is required";
    return;
  }
  const trackTypes = selectedTracks.value.length
    ? selectedTracks.value
    : trackOptions.map((item) => item.value);
  try {
    const resp: InitTracksResponse = await initRunTracks(runId.value, {
      track_types: trackTypes,
      recreate,
    });
    if (!activeTrackType.value || !trackTypes.includes(activeTrackType.value)) {
      activeTrackType.value = trackTypes[0] ?? "";
    }
    message.value = `track init done: ${resp.tracks.length} tracks`;
    await onLoadTrackDashboard();
  } catch (error) {
    errorMessage.value = `init tracks failed: ${stringifyError(error)}`;
  }
}

function formatRunTrackResult(resp: RunTrackResponse): string {
  if (resp.blocked_reason) {
    return `${resp.track_type} blocked: ${resp.blocked_reason}`;
  }
  return `${resp.track_type} jobs created: ${resp.jobs_created}`;
}

async function onRunActiveTrack(): Promise<void> {
  clearNotice();
  if (!runId.value || !activeTrackType.value) {
    errorMessage.value = "run_id and active_track are required";
    return;
  }
  try {
    const resp = await runTrack(runId.value, activeTrackType.value, { force: false });
    message.value = formatRunTrackResult(resp);
    await onLoadTrackDashboard();
  } catch (error) {
    errorMessage.value = `run track failed: ${stringifyError(error)}`;
  }
}

async function onRetryFailedInActiveTrack(): Promise<void> {
  clearNotice();
  if (!runId.value || !activeTrackType.value) {
    errorMessage.value = "run_id and active_track are required";
    return;
  }
  try {
    const resp = await runTrack(runId.value, activeTrackType.value, {
      only_failed: true,
      force: true,
    });
    message.value = formatRunTrackResult(resp);
    await onLoadTrackDashboard();
  } catch (error) {
    errorMessage.value = `retry failed units failed: ${stringifyError(error)}`;
  }
}

async function onRetryUnit(unit: TrackUnitItem): Promise<void> {
  clearNotice();
  if (!runId.value) {
    errorMessage.value = "run_id is required";
    return;
  }
  try {
    const resp = await retryTrackUnit(runId.value, unit.unit_id, {});
    message.value = `unit retried: ${resp.track_unit_id}`;
    await onLoadTrackDashboard();
  } catch (error) {
    errorMessage.value = `retry unit failed: ${stringifyError(error)}`;
  }
}

onMounted(() => {
  void onListNovels();
});

watch(activeTrackType, () => {
  void loadActiveTrackUnits();
});
</script>
