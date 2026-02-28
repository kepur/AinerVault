<template>
  <div class="chapter-workbench">
    <NCard title="SKILL 24 · Novel / Chapter Workspace" class="toolbar-card">
      <NGrid :cols="4" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:4 900:1">
          <NFormItem label="Tenant ID"><NInput v-model:value="tenantId" /></NFormItem>
        </NGridItem>
        <NGridItem span="0:4 900:1">
          <NFormItem label="Project ID"><NInput v-model:value="projectId" /></NFormItem>
        </NGridItem>
        <NGridItem span="0:4 900:1">
          <NFormItem label="Output Language"><NSelect v-model:value="targetLanguage" :options="languageOptions" filterable /></NFormItem>
        </NGridItem>
        <NGridItem span="0:4 900:1">
          <NSpace>
            <NButton @click="onLoadLanguagePolicy">加载语言策略</NButton>
            <NButton @click="onListNovels">刷新小说</NButton>
            <NButton v-if="selectedNovelId" @click="onListChapters">刷新章节</NButton>
          </NSpace>
        </NGridItem>
      </NGrid>
      <NSpace>
        <NTag type="info" :bordered="false">Novel: {{ selectedNovelTitle || "(未选择)" }}</NTag>
        <NTag type="warning" :bordered="false">Chapter: {{ selectedChapterTitle || "(未选择)" }}</NTag>
      </NSpace>
    </NCard>

    <NGrid :cols="24" :x-gap="12" :y-gap="12" responsive="screen" item-responsive>
      <NGridItem span="0:24 1200:6">
        <NCard title="小说列表" class="panel-card">
          <NSpace justify="space-between" align="center">
            <NInput v-model:value="novelKeyword" placeholder="按小说名过滤" />
            <NButton type="primary" @click="showNovelCreate = !showNovelCreate">新建小说</NButton>
          </NSpace>

          <div v-if="showNovelCreate" class="inline-form">
            <NFormItem label="Title"><NInput v-model:value="novelTitle" /></NFormItem>
            <NFormItem label="Default Language"><NInput v-model:value="novelLang" /></NFormItem>
            <NFormItem label="Summary">
              <NInput v-model:value="novelSummary" type="textarea" :autosize="{ minRows: 3, maxRows: 6 }" />
            </NFormItem>
            <NSpace>
              <NButton type="primary" @click="onCreateNovel">{{ t('common.create') }}</NButton>
              <NButton @click="showNovelCreate = false">收起</NButton>
            </NSpace>
          </div>

          <NDataTable :columns="novelColumns" :data="filteredNovels" :pagination="{ pageSize: 10 }" />
        </NCard>
      </NGridItem>

      <NGridItem span="0:24 1200:18">
        <NCard v-if="!selectedNovelId" :title="t('chapter.chapterMgmt')" class="panel-card">
          <NEmpty description="请先在左侧选择小说，再显示章节列表和编辑工作区。" />
        </NCard>

        <template v-else>
          <NCard :title="`章节列表 · ${selectedNovelTitle}`" class="panel-card">
            <NSpace justify="space-between" align="center">
              <NInput v-model:value="chapterKeyword" placeholder="按章节名或编号过滤" />
              <NSpace>
                <NButton @click="onListChapters">{{ t('common.refresh') }}</NButton>
                <NButton type="primary" @click="showChapterCreate = !showChapterCreate">新建章节</NButton>
              </NSpace>
            </NSpace>

            <div v-if="showChapterCreate" class="inline-form">
              <NGrid :cols="3" :x-gap="8" :y-gap="8" responsive="screen" item-responsive>
                <NGridItem span="0:3 900:1">
                  <NFormItem label="Chapter No"><NInputNumber v-model:value="newChapterNo" :min="1" style="width: 100%" /></NFormItem>
                </NGridItem>
                <NGridItem span="0:3 900:1">
                  <NFormItem label="Language"><NSelect v-model:value="newChapterLang" :options="languageOptions" filterable /></NFormItem>
                </NGridItem>
                <NGridItem span="0:3 900:1"><NFormItem label="Title"><NInput v-model:value="newChapterTitle" /></NFormItem></NGridItem>
              </NGrid>
              <NFormItem label="Markdown">
                <NInput v-model:value="newChapterMarkdown" type="textarea" :autosize="{ minRows: 8, maxRows: 14 }" />
              </NFormItem>
              <NSpace>
                <NButton type="primary" @click="onCreateChapter">创建并进入编辑</NButton>
                <NButton @click="showChapterCreate = false">收起</NButton>
              </NSpace>
            </div>

            <NDataTable :columns="chapterColumns" :data="filteredChapters" :pagination="{ pageSize: 12 }" />
          </NCard>

          <NCard v-if="selectedChapterId" :title="`章节编辑器 · ${selectedChapterTitle}`" class="panel-card editor-card">
            <NGrid :cols="2" :x-gap="8" :y-gap="8" responsive="screen" item-responsive>
              <NGridItem span="0:2 900:1"><NFormItem label="Language"><NSelect v-model:value="editChapterLang" :options="languageOptions" filterable /></NFormItem></NGridItem>
              <NGridItem span="0:2 900:1"><NFormItem label="Title"><NInput v-model:value="editChapterTitle" /></NFormItem></NGridItem>
            </NGrid>

            <NSpace>
              <NButton type="warning" @click="onUpdateChapter">保存章节</NButton>
              <NButton type="info" @click="onPreview(selectedChapterId)">预览 01~03</NButton>
              <NButton @click="onLoadRevisions(selectedChapterId)">修订历史</NButton>
              <NButton type="primary" @click="onAssistExpandChapter">一键 AI 扩写剧情</NButton>
            </NSpace>

            <div class="editor-split">
              <div class="editor-pane">
                <NFormItem label="Markdown 编辑区">
                  <NInput v-model:value="editChapterMarkdown" type="textarea" :autosize="{ minRows: 30, maxRows: 60 }" />
                </NFormItem>
              </div>
              <div class="preview-pane">
                <div class="markdown-preview" v-html="markdownPreviewHtml" />
              </div>
            </div>

            <NTabs type="line" animated>
              <NTabPane name="preview" :tab="t('chapter.previewResult')">
                <pre class="json-panel">{{ previewText }}</pre>
              </NTabPane>
              <NTabPane name="revisions" :tab="t('chapter.revisionHistory')">
                <pre class="json-panel">{{ revisionsText }}</pre>
              </NTabPane>
              <NTabPane name="assistant" :tab="t('chapter.aiExpandLog')">
                <pre class="json-panel">{{ assistText }}</pre>
              </NTabPane>
            </NTabs>
          </NCard>
        </template>
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
  NEmpty,
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
import { useI18n } from "@/composables/useI18n";


import {
  type ChapterResponse,
  type NovelResponse,
  assistExpandChapter,
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

const { t } = useI18n();

const tenantId = ref("default");
const projectId = ref("default");

const languageOptions = ref<SelectOption[]>([
  { label: "简体中文 (zh-CN)", value: "zh-CN" },
  { label: "English (en-US)", value: "en-US" },
  { label: "日本語 (ja-JP)", value: "ja-JP" },
]);
const targetLanguage = ref("en-US");

const showNovelCreate = ref(false);
const showChapterCreate = ref(false);

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
const assistText = ref("{}");

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

const selectedNovelTitle = computed(() =>
  novels.value.find((item) => item.id === selectedNovelId.value)?.title || ""
);

const selectedChapterTitle = computed(() => {
  const chapter = chapters.value.find((item) => item.id === selectedChapterId.value);
  if (!chapter) {
    return "";
  }
  return chapter.title || `Chapter ${chapter.chapter_no}`;
});

const markdownPreviewHtml = computed(() => renderMarkdownToHtml(editChapterMarkdown.value));

const novelColumns: DataTableColumns<NovelResponse> = [
  { title: "Title", key: "title" },
  { title: "Lang", key: "default_language_code", width: 100 },
  {
    title: "Action",
    key: "actions",
    width: 100,
    render: (row) => h(NButton, { size: "small", onClick: () => onSelectNovel(row.id) }, { default: () => "选择" }),
  },
];

const chapterColumns: DataTableColumns<ChapterResponse> = [
  { title: "No", key: "chapter_no", width: 70 },
  { title: "Title", key: "title" },
  { title: "Lang", key: "language_code", width: 100 },
  {
    title: "Actions",
    key: "actions",
    width: 190,
    render: (row) =>
      h(NSpace, { size: 6 }, {
        default: () => [
          h(NButton, { size: "tiny", onClick: () => onSelectChapter(row) }, { default: () => "编辑" }),
          h(NButton, { size: "tiny", type: "info", onClick: () => void onPreview(row.id) }, { default: () => "预览" }),
          h(NButton, { size: "tiny", onClick: () => void onLoadRevisions(row.id) }, { default: () => "历史" }),
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

function escapeHtml(raw: string): string {
  return raw
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/\"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function renderInlineMarkdown(line: string): string {
  let rendered = escapeHtml(line);
  rendered = rendered.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  rendered = rendered.replace(/`(.+?)`/g, "<code>$1</code>");
  return rendered;
}

function renderMarkdownToHtml(markdown: string): string {
  const lines = markdown.split("\n");
  const html: string[] = [];
  let inCode = false;
  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    if (line.startsWith("```")) {
      if (!inCode) {
        html.push("<pre><code>");
        inCode = true;
      } else {
        html.push("</code></pre>");
        inCode = false;
      }
      continue;
    }
    if (inCode) {
      html.push(`${escapeHtml(rawLine)}\n`);
      continue;
    }
    if (!line) {
      html.push("<br />");
      continue;
    }
    if (line.startsWith("### ")) {
      html.push(`<h3>${renderInlineMarkdown(line.slice(4))}</h3>`);
      continue;
    }
    if (line.startsWith("## ")) {
      html.push(`<h2>${renderInlineMarkdown(line.slice(3))}</h2>`);
      continue;
    }
    if (line.startsWith("# ")) {
      html.push(`<h1>${renderInlineMarkdown(line.slice(2))}</h1>`);
      continue;
    }
    if (line.startsWith("- ")) {
      html.push(`<li>${renderInlineMarkdown(line.slice(2))}</li>`);
      continue;
    }
    html.push(`<p>${renderInlineMarkdown(line)}</p>`);
  }
  return html.join("\n");
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
    showNovelCreate.value = false;
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
  showChapterCreate.value = false;
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
    showChapterCreate.value = false;
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

async function onAssistExpandChapter(): Promise<void> {
  clearNotice();
  if (!selectedChapterId.value) {
    errorMessage.value = "select chapter first";
    return;
  }
  try {
    const expanded = await assistExpandChapter(selectedChapterId.value, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      instruction: "扩展冲突与反转，增加镜头化动作细节和角色心理层次",
      style_hint: "电影化叙事，段落清晰",
      target_language: editChapterLang.value,
      max_tokens: 900,
    });
    editChapterMarkdown.value = expanded.expanded_markdown;
    assistText.value = toPrettyJson(expanded);
    message.value = `AI 扩写完成 (${expanded.mode}/${expanded.provider_used})`;
  } catch (error) {
    errorMessage.value = `assist expand failed: ${stringifyError(error)}`;
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
.chapter-workbench {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.toolbar-card,
.panel-card {
  border-radius: 10px;
}

.inline-form {
  margin: 12px 0;
  padding: 10px;
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fafafa;
}

.editor-card {
  min-height: 560px;
}

.editor-split {
  margin-top: 10px;
  display: grid;
  gap: 12px;
  grid-template-columns: minmax(340px, 1fr) minmax(340px, 1fr);
}

.editor-pane,
.preview-pane {
  min-height: 560px;
}

.preview-pane {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #ffffff;
  padding: 12px;
  overflow: auto;
}

.markdown-preview :deep(h1),
.markdown-preview :deep(h2),
.markdown-preview :deep(h3) {
  margin: 10px 0 8px;
}

.markdown-preview :deep(p),
.markdown-preview :deep(li) {
  margin: 6px 0;
  line-height: 1.62;
}

.markdown-preview :deep(code) {
  background: #f3f4f6;
  padding: 1px 4px;
  border-radius: 4px;
}

@media (max-width: 1200px) {
  .editor-split {
    grid-template-columns: 1fr;
  }
}
</style>
