<template>
  <div class="page-grid">
    <NCard title="SKILL 24 + 28 · Novel / Chapter / Task Run">
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Tenant ID">
            <NInput v-model:value="tenantId" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Project ID">
            <NInput v-model:value="projectId" />
          </NFormItem>
        </NGridItem>
      </NGrid>

      <NDivider />

      <NGrid :cols="3" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:3 640:1">
          <NFormItem label="输入语言">
            <NSelect v-model:value="sourceLanguage" :options="languageOptions" filterable />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:3 640:1">
          <NFormItem label="输出语言">
            <NSelect v-model:value="targetLanguage" :options="languageOptions" filterable />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:3 640:1">
          <NFormItem label="Locale / Language Context">
            <NInput v-model:value="localeContext" placeholder="en-US" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NSpace>
        <NButton @click="onLoadLanguagePolicy">加载语言策略</NButton>
      </NSpace>

      <NSpace>
        <NTag type="info" :bordered="false">Selected Novel: {{ selectedNovelId || "(none)" }}</NTag>
        <NTag type="warning" :bordered="false">Selected Chapter: {{ selectedChapterId || "(none)" }}</NTag>
      </NSpace>
    </NCard>

    <NCard title="Novel 管理">
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Title">
            <NInput v-model:value="novelTitle" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Default Language">
            <NInput v-model:value="novelLang" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NFormItem label="Summary">
        <NInput v-model:value="novelSummary" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" />
      </NFormItem>
      <NSpace>
        <NButton type="primary" @click="onCreateNovel">创建 Novel</NButton>
        <NButton @click="onListNovels">刷新 Novels</NButton>
      </NSpace>
      <NDataTable :columns="novelColumns" :data="novels" :pagination="{ pageSize: 6 }" />
    </NCard>

    <NCard title="Chapter 管理">
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Chapter No">
            <NInputNumber v-model:value="chapterNo" :min="1" style="width: 100%" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Language">
            <NSelect v-model:value="chapterLang" :options="languageOptions" filterable />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NFormItem label="Title">
        <NInput v-model:value="chapterTitle" />
      </NFormItem>
      <NFormItem label="Markdown Text">
        <NInput v-model:value="chapterMarkdown" type="textarea" :autosize="{ minRows: 6, maxRows: 10 }" />
      </NFormItem>
      <NSpace>
        <NButton type="primary" @click="onCreateChapter">创建 Chapter</NButton>
        <NButton @click="onListChapters">刷新 Chapters</NButton>
        <NButton type="warning" @click="onUpdateChapter">更新选中 Chapter</NButton>
      </NSpace>
      <NDataTable :columns="chapterColumns" :data="chapters" :pagination="{ pageSize: 8 }" />
    </NCard>

    <NCard title="Run Snapshot / 预览结果 / 修订历史">
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Run ID">
            <NInput v-model:value="runId" placeholder="run_xxx" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Culture Pack ID">
            <NInput v-model:value="culturePackId" placeholder="cn_wuxia" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Persona Ref">
            <NInput v-model:value="personaRef" placeholder="director_A@v1" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NSpace>
        <NButton type="primary" @click="onGetRunSnapshot">加载 Snapshot</NButton>
        <NButton @click="onLoadRevisions" :disabled="!selectedChapterId">加载修订历史</NButton>
      </NSpace>

      <NTabs type="line" animated>
        <NTabPane name="snapshot" tab="Run Snapshot">
          <pre class="json-panel">{{ runSnapshotText }}</pre>
        </NTabPane>
        <NTabPane name="preview" tab="Preview Result">
          <pre class="json-panel">{{ previewText }}</pre>
        </NTabPane>
        <NTabPane name="revision" tab="Chapter Revisions">
          <pre class="json-panel">{{ revisionsText }}</pre>
        </NTabPane>
      </NTabs>
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
  NDivider,
  NFormItem,
  NGrid,
  NGridItem,
  NInput,
  NInputNumber,
  NSelect,
  NSpace,
  NTabPane,
  NTabs,
  NTag,
  type DataTableColumns,
} from "naive-ui";

import {
  type ChapterResponse,
  type LanguageSettingsResponse,
  type NovelResponse,
  createChapter,
  createChapterTask,
  createNovel,
  getLanguageSettings,
  getRunSnapshot,
  listChapterRevisions,
  listChapters,
  listNovels,
  previewChapterPlan,
  updateChapter,
} from "@/api/product";

interface SelectOption {
  label: string;
  value: string;
}

const tenantId = ref("default");
const projectId = ref("default");

const sourceLanguage = ref("zh-CN");
const targetLanguage = ref("en-US");
const localeContext = ref("en-US");
const languageOptions = ref<SelectOption[]>([
  { label: "简体中文 (zh-CN)", value: "zh-CN" },
  { label: "English (en-US)", value: "en-US" },
  { label: "日本語 (ja-JP)", value: "ja-JP" },
]);

const novelTitle = ref("demo novel");
const novelSummary = ref("novel summary");
const novelLang = ref("zh-CN");
const novels = ref<NovelResponse[]>([]);
const selectedNovelId = ref("");

const chapterNo = ref<number | null>(1);
const chapterLang = ref("zh-CN");
const chapterTitle = ref("chapter-1");
const chapterMarkdown = ref(
  "这是一个可用于前端连调的章节文本。\n\n角色进入场景并展开冲突。\n\n镜头切换到对话与动作。"
);
const chapters = ref<ChapterResponse[]>([]);
const selectedChapterId = ref("");

const runId = ref("");
const culturePackId = ref("cn_wuxia");
const personaRef = ref("director_A@v1");

const runSnapshotText = ref("{}");
const previewText = ref("{}");
const revisionsText = ref("[]");

const message = ref("");
const errorMessage = ref("");

const novelColumns: DataTableColumns<NovelResponse> = [
  { title: "ID", key: "id" },
  { title: "Title", key: "title" },
  { title: "Language", key: "default_language_code" },
  {
    title: "Action",
    key: "actions",
    render: (row) =>
      h(
        NButton,
        {
          size: "small",
          onClick: () => onSelectNovel(row.id),
        },
        { default: () => "Select" }
      ),
  },
];

const chapterColumns: DataTableColumns<ChapterResponse> = [
  { title: "ID", key: "id" },
  { title: "No", key: "chapter_no" },
  { title: "Title", key: "title" },
  { title: "Lang", key: "language_code" },
  {
    title: "Actions",
    key: "actions",
    render: (row) =>
      h(NSpace, { size: 6 }, {
        default: () => [
          h(
            NButton,
            { size: "tiny", onClick: () => onSelectChapter(row) },
            { default: () => "Select" }
          ),
          h(
            NButton,
            { size: "tiny", type: "info", onClick: () => void onPreviewChapter(row.id) },
            { default: () => "Preview" }
          ),
          h(
            NButton,
            { size: "tiny", type: "primary", onClick: () => void onCreateTask(row.id) },
            { default: () => "Create Task" }
          ),
        ],
      }),
  },
];

function stringifyError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

function clearNotice(): void {
  message.value = "";
  errorMessage.value = "";
}

function toPrettyJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function fillLanguagesFromSettings(settings: LanguageSettingsResponse): void {
  const options = settings.enabled_languages
    .filter((item) => item.enabled)
    .map((item) => ({
      label: `${item.label} (${item.language_code})`,
      value: item.language_code,
    }));
  if (options.length > 0) {
    languageOptions.value = options;
  }
  sourceLanguage.value = settings.default_source_language;
  novelLang.value = settings.default_source_language;
  chapterLang.value = settings.default_source_language;
  if (settings.default_target_languages.length > 0) {
    targetLanguage.value = settings.default_target_languages[0];
    localeContext.value = settings.default_target_languages[0];
  }
}

async function onLoadLanguagePolicy(): Promise<void> {
  clearNotice();
  try {
    const settings = await getLanguageSettings(tenantId.value, projectId.value);
    fillLanguagesFromSettings(settings);
    message.value = "language settings loaded";
  } catch (error) {
    errorMessage.value = `load language settings failed: ${stringifyError(error)}`;
  }
}

async function onCreateNovel(): Promise<void> {
  clearNotice();
  try {
    const novel = await createNovel({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      title: novelTitle.value,
      summary: novelSummary.value,
      default_language_code: novelLang.value,
    });
    selectedNovelId.value = novel.id;
    message.value = `novel created: ${novel.id}`;
    await onListNovels();
  } catch (error) {
    errorMessage.value = `create novel failed: ${stringifyError(error)}`;
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

function onSelectNovel(novelId: string): void {
  selectedNovelId.value = novelId;
  void onListChapters();
}

async function onCreateChapter(): Promise<void> {
  clearNotice();
  if (!selectedNovelId.value) {
    errorMessage.value = "select a novel first";
    return;
  }
  if (chapterNo.value === null) {
    errorMessage.value = "chapter no is required";
    return;
  }
  try {
    const chapter = await createChapter(selectedNovelId.value, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      chapter_no: chapterNo.value,
      language_code: chapterLang.value,
      title: chapterTitle.value,
      markdown_text: chapterMarkdown.value,
    });
    selectedChapterId.value = chapter.id;
    message.value = `chapter created: ${chapter.id}`;
    await onListChapters();
  } catch (error) {
    errorMessage.value = `create chapter failed: ${stringifyError(error)}`;
  }
}

async function onListChapters(): Promise<void> {
  clearNotice();
  if (!selectedNovelId.value) {
    errorMessage.value = "select a novel first";
    return;
  }
  try {
    chapters.value = await listChapters(selectedNovelId.value);
  } catch (error) {
    errorMessage.value = `list chapters failed: ${stringifyError(error)}`;
  }
}

function onSelectChapter(chapter: ChapterResponse): void {
  selectedChapterId.value = chapter.id;
  chapterNo.value = chapter.chapter_no;
  chapterLang.value = chapter.language_code;
  chapterTitle.value = chapter.title || "";
  chapterMarkdown.value = chapter.markdown_text;
}

async function onUpdateChapter(): Promise<void> {
  clearNotice();
  if (!selectedChapterId.value) {
    errorMessage.value = "select a chapter first";
    return;
  }
  try {
    await updateChapter(selectedChapterId.value, {
      markdown_text: chapterMarkdown.value,
      title: chapterTitle.value,
      language_code: chapterLang.value,
      revision_note: "frontend_patch",
    });
    message.value = "chapter updated";
    await onListChapters();
  } catch (error) {
    errorMessage.value = `update chapter failed: ${stringifyError(error)}`;
  }
}

async function onPreviewChapter(chapterId: string): Promise<void> {
  clearNotice();
  try {
    const preview = await previewChapterPlan(chapterId, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      target_output_language: targetLanguage.value,
      target_locale: localeContext.value,
      genre: "wuxia",
      story_world_setting: "historical",
      culture_pack_id: culturePackId.value || undefined,
      persona_ref: personaRef.value || undefined,
    });
    previewText.value = toPrettyJson(preview);
    message.value = `preview run: ${preview.preview_run_id}`;
  } catch (error) {
    errorMessage.value = `preview failed: ${stringifyError(error)}`;
  }
}

async function onCreateTask(chapterId: string): Promise<void> {
  clearNotice();
  try {
    const task = await createChapterTask(chapterId, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      requested_quality: "standard",
      language_context: localeContext.value,
      payload: {
        culture_pack_id: culturePackId.value,
        persona_pack_version_id: personaRef.value,
        source_language: sourceLanguage.value,
        target_language: targetLanguage.value,
      },
    });
    runId.value = task.run_id;
    message.value = `task accepted: ${task.run_id}`;
  } catch (error) {
    errorMessage.value = `create task failed: ${stringifyError(error)}`;
  }
}

async function onGetRunSnapshot(): Promise<void> {
  clearNotice();
  if (!runId.value) {
    errorMessage.value = "run_id is required";
    return;
  }
  try {
    const snapshot = await getRunSnapshot(runId.value);
    runSnapshotText.value = toPrettyJson(snapshot);
  } catch (error) {
    errorMessage.value = `load snapshot failed: ${stringifyError(error)}`;
  }
}

async function onLoadRevisions(): Promise<void> {
  clearNotice();
  if (!selectedChapterId.value) {
    errorMessage.value = "select chapter first";
    return;
  }
  try {
    const rows = await listChapterRevisions(selectedChapterId.value);
    revisionsText.value = toPrettyJson(rows);
  } catch (error) {
    errorMessage.value = `load revisions failed: ${stringifyError(error)}`;
  }
}

onMounted(() => {
  void onLoadLanguagePolicy();
});
</script>
