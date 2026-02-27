<template>
  <div class="chapter-workbench">
    <NCard title="SKILL 24 · 章节工作区（Chapter Workspace）">
      <NGrid :cols="4" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:4 900:1"><NFormItem label="Tenant ID"><NInput v-model:value="tenantId" /></NFormItem></NGridItem>
        <NGridItem span="0:4 900:1"><NFormItem label="Project ID"><NInput v-model:value="projectId" /></NFormItem></NGridItem>
        <NGridItem span="0:4 900:1"><NFormItem label="小说"><NSelect v-model:value="selectedNovelId" :options="novelOptions" filterable @update:value="onNovelChanged" /></NFormItem></NGridItem>
        <NGridItem span="0:4 900:1"><NFormItem label="Output Language"><NSelect v-model:value="targetLanguage" :options="languageOptions" filterable /></NFormItem></NGridItem>
      </NGrid>
      <NSpace>
        <NButton @click="onLoadLanguagePolicy">语言策略</NButton>
        <NButton @click="onLoadNovels">刷新小说</NButton>
        <NButton v-if="selectedNovelId" @click="onListChapters">刷新章节</NButton>
        <NButton @click="goNovelLibrary">返回小说库</NButton>
      </NSpace>
    </NCard>

    <NCard v-if="!selectedNovelId" title="章节列表">
      <NEmpty description="未选择小说，请先从小说库选择。" />
    </NCard>

    <template v-else>
      <NCard :title="`章节列表 · ${selectedNovelTitle}`">
        <NSpace justify="space-between" align="center">
          <NInput v-model:value="chapterKeyword" placeholder="按章节标题或编号过滤" />
          <NButton type="primary" @click="showCreate = !showCreate">新建章节</NButton>
        </NSpace>

        <div v-if="showCreate" class="inline-form">
          <NGrid :cols="3" :x-gap="8" :y-gap="8" responsive="screen" item-responsive>
            <NGridItem span="0:3 900:1"><NFormItem label="Chapter No"><NInputNumber v-model:value="newChapterNo" :min="1" style="width: 100%" /></NFormItem></NGridItem>
            <NGridItem span="0:3 900:1"><NFormItem label="Language"><NSelect v-model:value="newChapterLang" :options="languageOptions" filterable /></NFormItem></NGridItem>
            <NGridItem span="0:3 900:1"><NFormItem label="Title"><NInput v-model:value="newChapterTitle" /></NFormItem></NGridItem>
          </NGrid>
          <NFormItem label="Markdown"><NInput v-model:value="newChapterMarkdown" type="textarea" :autosize="{ minRows: 8, maxRows: 12 }" /></NFormItem>
          <NSpace>
            <NButton type="primary" @click="onCreateChapter">创建并编辑</NButton>
            <NButton @click="showCreate = false">收起</NButton>
          </NSpace>
        </div>

        <NDataTable :columns="chapterColumns" :data="filteredChapters" :pagination="{ pageSize: 12 }" />
      </NCard>

      <NCard v-if="selectedChapterId" :title="`编辑章节 · ${selectedChapterTitle}`" class="editor-card">
        <NGrid :cols="2" :x-gap="8" :y-gap="8" responsive="screen" item-responsive>
          <NGridItem span="0:2 900:1"><NFormItem label="Language"><NSelect v-model:value="editChapterLang" :options="languageOptions" filterable /></NFormItem></NGridItem>
          <NGridItem span="0:2 900:1"><NFormItem label="Title"><NInput v-model:value="editChapterTitle" /></NFormItem></NGridItem>
        </NGrid>

        <!-- AI 扩写工具栏 -->
        <NCard size="small" style="margin-bottom: 10px; background: #f8f9fa; border: 1px solid #e8e8e8;">
          <NSpace align="center" wrap>
            <span style="font-weight: 600; color: #333;">💡 AI 扩写剧情</span>
            <NFormItem label="选择模型" style="margin-bottom: 0;">
              <NSelect
                v-model:value="selectedModelId"
                :options="modelOptions"
                placeholder="请选择 AI 模型"
                style="min-width: 260px;"
                filterable
              />
            </NFormItem>
            <NButton
              type="primary"
              :loading="isExpanding"
              :disabled="!selectedModelId || isExpanding"
              @click="onAssistExpandChapter"
            >
              {{ isExpanding ? '生成中...' : '一键 AI 扩写剧情' }}
            </NButton>
            <NTag v-if="availableModels.length === 0" type="warning" size="small">
              未检测到可用模型，请先在 Provider 中配置
            </NTag>
          </NSpace>
        </NCard>

        <NSpace style="margin-bottom: 8px;">
          <NButton type="warning" @click="onUpdateChapter">保存</NButton>
          <NButton type="info" @click="onPreview(selectedChapterId)">预览 01~03</NButton>
          <NButton @click="onLoadRevisions(selectedChapterId)">修订历史</NButton>
        </NSpace>

        <!-- 编辑区 + 预览区 -->
        <div class="editor-split">
          <div class="editor-pane">
            <NFormItem label="Markdown 编辑"><NInput v-model:value="editChapterMarkdown" type="textarea" :autosize="{ minRows: 30, maxRows: 60 }" /></NFormItem>
          </div>
          <div class="preview-pane">
            <!-- AI 扩写结果预览（实时显示，确认/取消） -->
            <div v-if="aiExpandedMarkdown" class="ai-preview-panel">
              <NSpace justify="space-between" align="center" style="margin-bottom: 8px;">
                <span style="font-weight: 600; color: #1677ff;">🤖 AI 扩写预览</span>
                <NSpace>
                  <NButton type="primary" size="small" @click="onAcceptExpand">✅ 确认保存</NButton>
                  <NButton size="small" @click="onCancelExpand">❌ 取消</NButton>
                </NSpace>
              </NSpace>
              <NDivider style="margin: 6px 0;" />
              <div class="markdown-preview" v-html="renderMarkdownToHtml(aiExpandedMarkdown)" />
            </div>
            <!-- 正常预览 -->
            <div v-else>
              <div v-if="isExpanding" style="text-align: center; padding: 40px;">
                <NSpin size="large" />
                <p style="color: #999; margin-top: 10px;">AI 正在创作中，请稍候...</p>
              </div>
              <div v-else class="markdown-preview" v-html="markdownPreviewHtml" />
            </div>
          </div>
        </div>

        <NTabs type="line" animated>
          <NTabPane name="preview" tab="预览结果"><pre class="json-panel">{{ previewText }}</pre></NTabPane>
          <NTabPane name="revision" tab="修订历史"><pre class="json-panel">{{ revisionsText }}</pre></NTabPane>
          <NTabPane name="assistant" tab="AI 扩写日志"><pre class="json-panel">{{ assistText }}</pre></NTabPane>
        </NTabs>
      </NCard>
    </template>

    <NAlert v-if="message" type="success" :show-icon="true">{{ message }}</NAlert>
    <NAlert v-if="errorMessage" type="error" :show-icon="true">{{ errorMessage }}</NAlert>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
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
  NDivider,
  NTag,
  NSpin,
  type DataTableColumns,
} from "naive-ui";

import {
  assistExpandChapter,
  createChapter,
  getLanguageSettings,
  listAvailableModels,
  listChapterRevisions,
  listChapters,
  listNovels,
  previewChapterPlan,
  updateChapter,
  type ChapterResponse,
  type NovelResponse,
} from "@/api/product";

const STORAGE_KEY = "studio_selected_novel_id";

interface SelectOption {
  label: string;
  value: string;
}

const route = useRoute();
const router = useRouter();
const tenantId = ref("default");
const projectId = ref("default");
const targetLanguage = ref("en-US");
const novels = ref<NovelResponse[]>([]);
const selectedNovelId = ref("");
const chapters = ref<ChapterResponse[]>([]);

const languageOptions = ref<SelectOption[]>([
  { label: "简体中文 (zh-CN)", value: "zh-CN" },
  { label: "English (en-US)", value: "en-US" },
  { label: "日本語 (ja-JP)", value: "ja-JP" },
]);

const chapterKeyword = ref("");
const showCreate = ref(false);
const newChapterNo = ref<number | null>(1);
const newChapterLang = ref("zh-CN");
const newChapterTitle = ref("chapter-1");
const newChapterMarkdown = ref("章节内容");

const selectedChapterId = ref("");
const editChapterLang = ref("zh-CN");
const editChapterTitle = ref("");
const editChapterMarkdown = ref("");

const previewText = ref("{}");
const revisionsText = ref("[]");
const assistText = ref("{}");
const message = ref("");
const errorMessage = ref("");

// AI 扩写相关状态
const availableModels = ref<{ id: string; name: string; endpoint: string | null; auth_mode: string | null }[]>([]);
const selectedModelId = ref("");
const aiExpandedMarkdown = ref("");  // AI 扩写结果暂存（实时预览）
const isExpanding = ref(false);

const novelOptions = computed(() => novels.value.map((item) => ({ label: item.title, value: item.id })));

const selectedNovelTitle = computed(() => novels.value.find((item) => item.id === selectedNovelId.value)?.title || "");

const modelOptions = computed(() =>
  availableModels.value.map((m) => ({
    label: `${m.name}${m.endpoint ? ` (${m.endpoint})` : ""}`,
    value: m.id,
  }))
);

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

const selectedChapterTitle = computed(() => {
  const chapter = chapters.value.find((item) => item.id === selectedChapterId.value);
  if (!chapter) {
    return "";
  }
  return chapter.title || `Chapter ${chapter.chapter_no}`;
});

const markdownPreviewHtml = computed(() => renderMarkdownToHtml(editChapterMarkdown.value));

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

function clearNotice(): void {
  message.value = "";
  errorMessage.value = "";
}

function stringifyError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
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
  newChapterLang.value = editChapterLang.value || newChapterLang.value;
  newChapterMarkdown.value = "章节内容";
}

function goNovelLibrary(): void {
  void router.push({ name: "studio-novels" });
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
    editChapterLang.value = settings.default_source_language;
    newChapterLang.value = settings.default_source_language;
  } catch (error) {
    errorMessage.value = `load language settings failed: ${stringifyError(error)}`;
  }
}

async function onLoadNovels(): Promise<void> {
  clearNotice();
  try {
    novels.value = await listNovels(tenantId.value, projectId.value);
    if (selectedNovelId.value && !novels.value.some((item) => item.id === selectedNovelId.value)) {
      selectedNovelId.value = "";
      chapters.value = [];
      selectedChapterId.value = "";
    }
  } catch (error) {
    errorMessage.value = `load novels failed: ${stringifyError(error)}`;
  }
}

async function onNovelChanged(novelId: string): Promise<void> {
  selectedNovelId.value = novelId;
  localStorage.setItem(STORAGE_KEY, novelId);
  selectedChapterId.value = "";
  editChapterMarkdown.value = "";
  await onListChapters();
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

async function onCreateChapter(): Promise<void> {
  clearNotice();
  if (!selectedNovelId.value || newChapterNo.value === null) {
    errorMessage.value = "select novel and chapter no first";
    return;
  }
  try {
    const created = await createChapter(selectedNovelId.value, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      chapter_no: newChapterNo.value,
      language_code: newChapterLang.value,
      title: newChapterTitle.value,
      markdown_text: newChapterMarkdown.value,
    });
    await onListChapters();
    const chapter = chapters.value.find((item) => item.id === created.id);
    if (chapter) {
      syncEditorFromChapter(chapter);
    }
    showCreate.value = false;
    message.value = `chapter created: ${created.id}`;
  } catch (error) {
    errorMessage.value = `create chapter failed: ${stringifyError(error)}`;
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
      revision_note: "workspace edit",
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

async function onLoadModels(): Promise<void> {
  try {
    availableModels.value = await listAvailableModels(tenantId.value, projectId.value);
    if (availableModels.value.length > 0 && !selectedModelId.value) {
      selectedModelId.value = availableModels.value[0].id;
    }
  } catch (error) {
    errorMessage.value = `load models failed: ${stringifyError(error)}`;
  }
}

async function onAssistExpandChapter(): Promise<void> {
  clearNotice();
  if (!selectedChapterId.value) {
    errorMessage.value = "请先选择章节";
    return;
  }
  if (!selectedModelId.value) {
    errorMessage.value = "请先选择 AI 模型";
    return;
  }
  isExpanding.value = true;
  aiExpandedMarkdown.value = "";
  try {
    const expanded = await assistExpandChapter(selectedChapterId.value, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      model_provider_id: selectedModelId.value,
      instruction: "扩展冲突与反转，增加镜头化动作细节和角色心理层次",
      style_hint: "电影化叙事，段落清晰",
      target_language: editChapterLang.value,
      max_tokens: 900,
    });
    aiExpandedMarkdown.value = expanded.expanded_markdown;
    assistText.value = toPrettyJson(expanded);
    message.value = `AI 扩写完成 (${expanded.mode} · ${expanded.provider_used})`;
  } catch (error) {
    errorMessage.value = `assist expand failed: ${stringifyError(error)}`;
  } finally {
    isExpanding.value = false;
  }
}

async function onAcceptExpand(): Promise<void> {
  if (!aiExpandedMarkdown.value || !selectedChapterId.value) return;
  editChapterMarkdown.value = aiExpandedMarkdown.value;
  aiExpandedMarkdown.value = "";
  await onUpdateChapter();
  message.value = "AI 扩写内容已保存";
}

function onCancelExpand(): void {
  aiExpandedMarkdown.value = "";
  clearNotice();
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
  const queryNovelId = String(route.query.novelId || "").trim();
  const storedNovelId = localStorage.getItem(STORAGE_KEY) || "";
  selectedNovelId.value = queryNovelId || storedNovelId;
  void onLoadLanguagePolicy();
  void onLoadModels();
  void onLoadNovels().then(() => {
    if (selectedNovelId.value) {
      void onListChapters();
    }
  });
});
</script>

<style scoped>
.chapter-workbench {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.inline-form {
  margin-top: 10px;
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

.preview-pane {
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  background: #fff;
  padding: 12px;
  overflow: auto;
}

.ai-preview-panel {
  border: 2px solid #1677ff;
  border-radius: 8px;
  background: #f0f5ff;
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
