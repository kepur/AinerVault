<template>
  <div class="page-grid">
    <NCard title="SKILL 24 · Novel / Chapter 分层管理">
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
          <NFormItem label="Output Language">
            <NSelect v-model:value="targetLanguage" :options="languageOptions" filterable />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:4 900:1">
          <NFormItem label="Actions">
            <NSpace>
              <NButton @click="onLoadLanguagePolicy">加载语言策略</NButton>
              <NButton @click="onListNovels">刷新小说列表</NButton>
            </NSpace>
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NSpace>
        <NTag type="info" :bordered="false">Selected Novel: {{ selectedNovelId || "(none)" }}</NTag>
        <NTag type="warning" :bordered="false">Selected Chapter: {{ selectedChapterId || "(none)" }}</NTag>
      </NSpace>
    </NCard>

    <NGrid :cols="3" :x-gap="12" :y-gap="12" responsive="screen" item-responsive>
      <NGridItem span="0:3 1200:1">
        <NCard title="小说列表">
          <NFormItem label="关键词过滤">
            <NInput v-model:value="novelKeyword" placeholder="title keyword" />
          </NFormItem>
          <NDataTable :columns="novelColumns" :data="filteredNovels" :pagination="{ pageSize: 8 }" />
        </NCard>

        <NCard title="新建小说" class="sub-card">
          <NFormItem label="Title">
            <NInput v-model:value="novelTitle" />
          </NFormItem>
          <NFormItem label="Default Language">
            <NInput v-model:value="novelLang" />
          </NFormItem>
          <NFormItem label="Summary">
            <NInput v-model:value="novelSummary" type="textarea" :autosize="{ minRows: 3, maxRows: 5 }" />
          </NFormItem>
          <NButton type="primary" @click="onCreateNovel">创建 Novel</NButton>
        </NCard>
      </NGridItem>

      <NGridItem span="0:3 1200:1">
        <NCard title="章节列表">
          <NAlert v-if="!selectedNovelId" type="info" :show-icon="true">先在左侧选择小说后查看章节</NAlert>
          <template v-else>
            <NFormItem label="关键词过滤">
              <NInput v-model:value="chapterKeyword" placeholder="title keyword" />
            </NFormItem>
            <NSpace>
              <NButton @click="onListChapters">刷新章节列表</NButton>
            </NSpace>
            <NDataTable :columns="chapterColumns" :data="filteredChapters" :pagination="{ pageSize: 10 }" />
          </template>
        </NCard>

        <NCard title="新建章节" class="sub-card">
          <NAlert v-if="!selectedNovelId" type="warning" :show-icon="true">未选择小说，无法新建章节</NAlert>
          <template v-else>
            <NGrid :cols="3" :x-gap="8" :y-gap="8" responsive="screen" item-responsive>
              <NGridItem span="0:3 900:1">
                <NFormItem label="Chapter No">
                  <NInputNumber v-model:value="newChapterNo" :min="1" style="width: 100%" />
                </NFormItem>
              </NGridItem>
              <NGridItem span="0:3 900:1">
                <NFormItem label="Language">
                  <NSelect v-model:value="newChapterLang" :options="languageOptions" filterable />
                </NFormItem>
              </NGridItem>
              <NGridItem span="0:3 900:1">
                <NFormItem label="Title">
                  <NInput v-model:value="newChapterTitle" />
                </NFormItem>
              </NGridItem>
            </NGrid>
            <NFormItem label="Markdown">
              <NInput v-model:value="newChapterMarkdown" type="textarea" :autosize="{ minRows: 6, maxRows: 10 }" />
            </NFormItem>
            <NButton type="primary" @click="onCreateChapter">创建 Chapter</NButton>
          </template>
        </NCard>
      </NGridItem>

      <NGridItem span="0:3 1200:1">
        <NCard title="章节编辑 / 预览 / 修订历史">
          <NAlert v-if="!selectedChapterId" type="info" :show-icon="true">在中间章节列表点 Select 后进入编辑态</NAlert>
          <template v-else>
            <NGrid :cols="2" :x-gap="8" :y-gap="8" responsive="screen" item-responsive>
              <NGridItem span="0:2 900:1">
                <NFormItem label="Language">
                  <NSelect v-model:value="editChapterLang" :options="languageOptions" filterable />
                </NFormItem>
              </NGridItem>
              <NGridItem span="0:2 900:1">
                <NFormItem label="Title">
                  <NInput v-model:value="editChapterTitle" />
                </NFormItem>
              </NGridItem>
            </NGrid>
            <NFormItem label="Markdown">
              <NInput v-model:value="editChapterMarkdown" type="textarea" :autosize="{ minRows: 10, maxRows: 14 }" />
            </NFormItem>
            <NSpace>
              <NButton type="warning" @click="onUpdateChapter">保存章节</NButton>
              <NButton type="info" @click="onPreview(selectedChapterId)">预览 01~03</NButton>
              <NButton @click="onLoadRevisions(selectedChapterId)">加载修订历史</NButton>
            </NSpace>
          </template>

          <NTabs type="line" animated>
            <NTabPane name="preview" tab="Preview Result">
              <pre class="json-panel">{{ previewText }}</pre>
            </NTabPane>
            <NTabPane name="revision" tab="Revision History">
              <pre class="json-panel">{{ revisionsText }}</pre>
            </NTabPane>
          </NTabs>
        </NCard>
      </NGridItem>
    </NGrid>

    <NAlert v-if="message" type="success" :show-icon="true">{{ message }}</NAlert>
    <NAlert v-if="errorMessage" type="error" :show-icon="true">{{ errorMessage }}</NAlert>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref } from "vue";
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

const novelKeyword = ref("");
const chapterKeyword = ref("");

const novelTitle = ref("demo novel");
const novelSummary = ref("novel summary");
const novelLang = ref("zh-CN");
const novels = ref<NovelResponse[]>([]);
const selectedNovelId = ref("");

const newChapterNo = ref<number | null>(1);
const newChapterLang = ref("zh-CN");
const newChapterTitle = ref("chapter-1");
const newChapterMarkdown = ref("章节内容");

const chapters = ref<ChapterResponse[]>([]);
const selectedChapterId = ref("");
const editChapterLang = ref("zh-CN");
const editChapterTitle = ref("");
const editChapterMarkdown = ref("");

const previewText = ref("{}");
const revisionsText = ref("[]");

const message = ref("");
const errorMessage = ref("");

const filteredNovels = computed(() => {
  const keyword = novelKeyword.value.trim().toLowerCase();
  if (!keyword) {
    return novels.value;
  }
  return novels.value.filter((item) => item.title.toLowerCase().includes(keyword));
});

const filteredChapters = computed(() => {
  const keyword = chapterKeyword.value.trim().toLowerCase();
  if (!keyword) {
    return chapters.value;
  }
  return chapters.value.filter((item) => {
    const title = (item.title || "").toLowerCase();
    return title.includes(keyword) || String(item.chapter_no).includes(keyword);
  });
});

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

function syncEditorFromChapter(chapter: ChapterResponse): void {
  selectedChapterId.value = chapter.id;
  editChapterTitle.value = chapter.title || "";
  editChapterLang.value = chapter.language_code;
  editChapterMarkdown.value = chapter.markdown_text;
}

function resetChapterCreateForm(): void {
  newChapterNo.value = (chapters.value[chapters.value.length - 1]?.chapter_no || 0) + 1;
  newChapterTitle.value = `chapter-${newChapterNo.value ?? 1}`;
  newChapterMarkdown.value = "章节内容";
  newChapterLang.value = novelLang.value;
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
    newChapterLang.value = settings.default_source_language;
    editChapterLang.value = settings.default_source_language;
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
    await onListNovels();
    onSelectNovel(novel.id);
    message.value = `novel created: ${novel.id}`;
  } catch (error) {
    errorMessage.value = `create novel failed: ${stringifyError(error)}`;
  }
}

async function onListNovels(): Promise<void> {
  clearNotice();
  try {
    novels.value = await listNovels(tenantId.value, projectId.value);
    if (selectedNovelId.value && !novels.value.some((item) => item.id === selectedNovelId.value)) {
      selectedNovelId.value = "";
      chapters.value = [];
      selectedChapterId.value = "";
    }
  } catch (error) {
    errorMessage.value = `list novels failed: ${stringifyError(error)}`;
  }
}

function onSelectNovel(novelId: string): void {
  selectedNovelId.value = novelId;
  selectedChapterId.value = "";
  editChapterTitle.value = "";
  editChapterMarkdown.value = "";
  void onListChapters();
}

async function onCreateChapter(): Promise<void> {
  clearNotice();
  if (!selectedNovelId.value || newChapterNo.value === null) {
    errorMessage.value = "select novel and chapter no first";
    return;
  }
  try {
    const chapter = await createChapter(selectedNovelId.value, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      chapter_no: newChapterNo.value,
      language_code: newChapterLang.value,
      title: newChapterTitle.value,
      markdown_text: newChapterMarkdown.value,
    });
    await onListChapters();
    const created = chapters.value.find((item) => item.id === chapter.id);
    if (created) {
      syncEditorFromChapter(created);
    }
    resetChapterCreateForm();
    message.value = `chapter created: ${chapter.id}`;
  } catch (error) {
    errorMessage.value = `create chapter failed: ${stringifyError(error)}`;
  }
}

async function onListChapters(): Promise<void> {
  clearNotice();
  if (!selectedNovelId.value) {
    chapters.value = [];
    return;
  }
  try {
    chapters.value = await listChapters(selectedNovelId.value);
    resetChapterCreateForm();
  } catch (error) {
    errorMessage.value = `list chapters failed: ${stringifyError(error)}`;
  }
}

function onSelectChapter(chapter: ChapterResponse): void {
  syncEditorFromChapter(chapter);
}

async function onUpdateChapter(): Promise<void> {
  clearNotice();
  if (!selectedChapterId.value) {
    errorMessage.value = "select chapter first";
    return;
  }
  try {
    await updateChapter(selectedChapterId.value, {
      title: editChapterTitle.value,
      language_code: editChapterLang.value,
      markdown_text: editChapterMarkdown.value,
      revision_note: "studio edit",
    });
    await onListChapters();
    const current = chapters.value.find((item) => item.id === selectedChapterId.value);
    if (current) {
      syncEditorFromChapter(current);
    }
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

<style scoped>
.sub-card {
  margin-top: 12px;
}
</style>
