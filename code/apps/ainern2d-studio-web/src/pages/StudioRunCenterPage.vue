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
      </NGrid>
      <NSpace>
        <NButton type="primary" @click="onCreateTask">创建 Task / Run</NButton>
        <NButton @click="onLoadSnapshot" :disabled="!runId">加载 Run Snapshot</NButton>
        <NButton type="info" @click="onLoadRunObservability" :disabled="!runId">加载运行观测</NButton>
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

    <NAlert v-if="message" type="success" :show-icon="true">{{ message }}</NAlert>
    <NAlert v-if="errorMessage" type="error" :show-icon="true">{{ errorMessage }}</NAlert>
  </div>
</template>

<script setup lang="ts">
import { h, onMounted, ref } from "vue";
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
  NSpace,
  NTag,
  NText,
  type DataTableColumns,
} from "naive-ui";

import {
  type ChapterResponse,
  type NovelResponse,
  type PolicyStackReplayItem,
  type PromptPlanReplayItem,
  type RunDetailResponse,
  createChapterTask,
  getRunDetail,
  getRunPolicyStacks,
  getRunPromptPlans,
  getRunSnapshot,
  listChapters,
  listNovels,
} from "@/api/product";

const tenantId = ref("default");
const projectId = ref("default");
const chapterId = ref("");
const requestedQuality = ref("standard");
const languageContext = ref("en-US");
const culturePackId = ref("cn_wuxia");
const personaRef = ref("director_A@v1");

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
      },
    });
    runId.value = accepted.run_id;
    message.value = `run created: ${accepted.run_id}`;
    await onLoadSnapshot();
    await onLoadRunObservability();
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

onMounted(() => {
  void onListNovels();
});
</script>
