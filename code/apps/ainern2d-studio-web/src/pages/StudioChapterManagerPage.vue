<template>
  <div class="page-grid">
    <NCard title="SKILL 24 · Novel / Chapter 管理">
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
          <NFormItem label="Output Language">
            <NSelect v-model:value="targetLanguage" :options="languageOptions" filterable />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NSpace>
        <NButton @click="onLoadLanguagePolicy">加载语言策略</NButton>
        <NTag type="info" :bordered="false">Selected Novel: {{ selectedNovelId || "(none)" }}</NTag>
        <NTag type="warning" :bordered="false">Selected Chapter: {{ selectedChapterId || "(none)" }}</NTag>
      </NSpace>
    </NCard>

    <NCard title="Novel CRUD">
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 900:1">
          <NFormItem label="Title">
            <NInput v-model:value="novelTitle" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 900:1">
          <NFormItem label="Default Language">
            <NInput v-model:value="novelLang" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NFormItem label="Summary">
        <NInput v-model:value="novelSummary" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" />
      </NFormItem>
      <NSpace>
        <NButton type="primary" @click="onCreateNovel">新增 Novel</NButton>
        <NButton @click="onListNovels">刷新列表</NButton>
      </NSpace>
      <NDataTable :columns="novelColumns" :data="novels" :pagination="{ pageSize: 6 }" />
    </NCard>

    <NCard title="Chapter CRUD + Preview">
      <NGrid :cols="3" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Chapter No">
            <NInputNumber v-model:value="chapterNo" :min="1" style="width: 100%" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Language">
            <NSelect v-model:value="chapterLang" :options="languageOptions" filterable />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Title">
            <NInput v-model:value="chapterTitle" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NFormItem label="Markdown">
        <NInput v-model:value="chapterMarkdown" type="textarea" :autosize="{ minRows: 8, maxRows: 12 }" />
      </NFormItem>
      <NSpace>
        <NButton type="primary" @click="onCreateChapter">新增 Chapter</NButton>
        <NButton @click="onListChapters">刷新列表</NButton>
        <NButton type="warning" @click="onUpdateChapter">更新选中 Chapter</NButton>
      </NSpace>
      <NDataTable :columns="chapterColumns" :data="chapters" :pagination="{ pageSize: 8 }" />

      <NTabs type="line" animated>
        <NTabPane name="preview" tab="Preview Result">
          <pre class="json-panel">{{ previewText }}</pre>
        </NTabPane>
        <NTabPane name="revision" tab="Revision History">
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
  type NovelResponse,
  createChapter,
  createNovel,
  getLanguageSettings,
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

const languageOptions = ref<SelectOption[]>([
  { label: "简体中文 (zh-CN)", value: "zh-CN" },
  { label: "English (en-US)", value: "en-US" },
  { label: "日本語 (ja-JP)", value: "ja-JP" },
]);
const targetLanguage = ref("en-US");

const novelTitle = ref("demo novel");
const novelSummary = ref("novel summary");
const novelLang = ref("zh-CN");
const novels = ref<NovelResponse[]>([]);
const selectedNovelId = ref("");

const chapterNo = ref<number | null>(1);
const chapterLang = ref("zh-CN");
const chapterTitle = ref("chapter-1");
const chapterMarkdown = ref("章节内容");
const chapters = ref<ChapterResponse[]>([]);
const selectedChapterId = ref("");

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
    render: (row) => h(NButton, { size: "small", onClick: () => onSelectNovel(row.id) }, { default: () => "Select" }),
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
          h(NButton, { size: "tiny", onClick: () => onSelectChapter(row) }, { default: () => "Select" }),
          h(NButton, { size: "tiny", type: "info", onClick: () => void onPreview(row.id) }, { default: () => "Preview" }),
          h(NButton, { size: "tiny", onClick: () => void onLoadRevisions(row.id) }, { default: () => "Revisions" }),
        ],
      }),
  },
];

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

async function onLoadLanguagePolicy(): Promise<void> {
  clearNotice();
  try {
    const settings = await getLanguageSettings(tenantId.value, projectId.value);
    const options = settings.enabled_languages
      .filter((item) => item.enabled)
      .map((item) => ({ label: `${item.label} (${item.language_code})`, value: item.language_code }));
    if (options.length > 0) {
      languageOptions.value = options;
    }
    targetLanguage.value = settings.default_target_languages[0] || targetLanguage.value;
    novelLang.value = settings.default_source_language;
    chapterLang.value = settings.default_source_language;
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
    await onListNovels();
    message.value = `novel created: ${novel.id}`;
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
  if (!selectedNovelId.value || chapterNo.value === null) {
    errorMessage.value = "select novel and chapter no first";
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
    await onListChapters();
    message.value = `chapter created: ${chapter.id}`;
  } catch (error) {
    errorMessage.value = `create chapter failed: ${stringifyError(error)}`;
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

function onSelectChapter(chapter: ChapterResponse): void {
  selectedChapterId.value = chapter.id;
  chapterTitle.value = chapter.title || "";
  chapterLang.value = chapter.language_code;
  chapterMarkdown.value = chapter.markdown_text;
  chapterNo.value = chapter.chapter_no;
}

async function onUpdateChapter(): Promise<void> {
  clearNotice();
  if (!selectedChapterId.value) {
    errorMessage.value = "select chapter first";
    return;
  }
  try {
    await updateChapter(selectedChapterId.value, {
      title: chapterTitle.value,
      language_code: chapterLang.value,
      markdown_text: chapterMarkdown.value,
      revision_note: "studio edit",
    });
    await onListChapters();
    message.value = "chapter updated";
  } catch (error) {
    errorMessage.value = `update chapter failed: ${stringifyError(error)}`;
  }
}

async function onPreview(chapterId: string): Promise<void> {
  clearNotice();
  try {
    const preview = await previewChapterPlan(chapterId, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      target_output_language: targetLanguage.value,
      target_locale: targetLanguage.value,
    });
    previewText.value = toPrettyJson(preview);
    message.value = "preview generated";
  } catch (error) {
    errorMessage.value = `preview failed: ${stringifyError(error)}`;
  }
}

async function onLoadRevisions(chapterId = selectedChapterId.value): Promise<void> {
  clearNotice();
  if (!chapterId) {
    errorMessage.value = "select chapter first";
    return;
  }
  try {
    revisionsText.value = toPrettyJson(await listChapterRevisions(chapterId));
  } catch (error) {
    errorMessage.value = `load revisions failed: ${stringifyError(error)}`;
  }
}

onMounted(() => {
  void onLoadLanguagePolicy();
  void onListNovels();
});
</script>
