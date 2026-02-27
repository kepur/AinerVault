<template>
  <div class="page-grid">
    <NCard title="SKILL 28 · Task / Run 运行中心">
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
      </NSpace>
      <NSpace>
        <NTag type="success" :bordered="false">Run ID: {{ runId || "(none)" }}</NTag>
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

    <NAlert v-if="message" type="success" :show-icon="true">{{ message }}</NAlert>
    <NAlert v-if="errorMessage" type="error" :show-icon="true">{{ errorMessage }}</NAlert>
  </div>
</template>

<script setup lang="ts">
import { h, ref } from "vue";
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
  type DataTableColumns,
} from "naive-ui";

import {
  type ChapterResponse,
  type NovelResponse,
  createChapterTask,
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
const snapshotText = ref("{}");

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
      h(NButton, { size: "small", onClick: () => {
        selectedNovelId.value = row.id;
        void onListChapters();
      } }, { default: () => "Use" }),
  },
];

const chapterColumns: DataTableColumns<ChapterResponse> = [
  { title: "Chapter ID", key: "id" },
  { title: "No", key: "chapter_no" },
  { title: "Title", key: "title" },
  {
    title: "Action",
    key: "action",
    render: (row) => h(NButton, { size: "small", type: "info", onClick: () => {
      chapterId.value = row.id;
    } }, { default: () => "Use" }),
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
</script>
