<template>
  <div class="chapter-editor-container">
    <!-- 顶部工具栏 -->
    <div class="editor-header">
      <div class="header-left">
        <button class="btn-back" @click="goBack">← 返回</button>
        <h1 class="chapter-title">{{ chapter?.title || `第 ${chapter?.chapter_no} 章` }}</h1>
        <span v-if="isDirty" class="dirty-badge">未保存</span>
      </div>

      <div class="header-right">
        <!-- AI 模型选择 -->
        <select v-model="selectedModelId" class="model-selector">
          <option value="" disabled>选择模型...</option>
          <option v-for="m in availableModels" :key="m.id" :value="m.id">
            {{ m.name }}{{ m.endpoint ? ` (${m.endpoint})` : '' }}
          </option>
        </select>

        <!-- 扩写模式 -->
        <select v-model="expandMode" class="expand-mode-selector" :disabled="!selectedModelId">
          <option value="expand">扩写</option>
          <option value="complete">补全</option>
          <option value="rewrite">改写</option>
          <option value="polish">润色</option>
        </select>

        <!-- AI 扩写按钮 -->
        <button
          class="btn-ai-assistant"
          :disabled="!selectedModelId || isExpanding"
          @click="onAssistExpand"
        >
          {{ isExpanding ? '⏳ 生成中...' : '💡 AI扩写' }}
        </button>

        <!-- 保存 -->
        <button class="btn-save" :disabled="isSaving" @click="onSave">
          {{ isSaving ? '保存中...' : '保存' }}
        </button>
      </div>
    </div>

    <!-- 错误/成功提示 -->
    <div v-if="errorMsg" class="notice-bar notice-error">{{ errorMsg }}</div>
    <div v-if="successMsg" class="notice-bar notice-success">{{ successMsg }}</div>

    <!-- 加载中 -->
    <div v-if="isLoading" class="loading-placeholder">加载章节中...</div>

    <template v-else-if="chapter">
      <!-- 元数据行 -->
      <div class="meta-bar">
        <label>标题
          <input v-model="editTitle" class="meta-input" placeholder="章节标题" />
        </label>
        <label>语言
          <select v-model="editLang" class="meta-select">
            <option value="zh-CN">简体中文</option>
            <option value="en-US">English</option>
            <option value="ja-JP">日本語</option>
          </select>
        </label>
        <label>章节号 <span class="meta-readonly">{{ chapter.chapter_no }}</span></label>
      </div>

      <!-- 编辑区 + 预览区 -->
      <div class="editor-content">
        <!-- 左侧：Markdown 编辑 -->
        <div class="editor-pane">
          <textarea
            v-model="markdownText"
            class="markdown-editor"
            placeholder="在这里写下您的故事..."
            @input="isDirty = true"
          />
        </div>

        <!-- 右侧：实时预览 / AI 建议 -->
        <div class="preview-pane">
          <!-- AI 扩写预览 -->
          <template v-if="aiSuggestion">
            <div class="ai-suggestion-panel">
              <div class="suggestion-header">
                <span>🤖 AI扩写建议</span>
                <div style="display:flex;gap:8px">
                  <button class="btn-accept" @click="onAcceptExpand">✅ 接受并保存</button>
                  <button class="btn-reject" @click="aiSuggestion = ''">❌ 丢弃</button>
                </div>
              </div>
              <!-- eslint-disable-next-line vue/no-v-html -->
              <div class="suggestion-content" v-html="renderMarkdown(aiSuggestion)" />
            </div>
          </template>

          <!-- 正常预览 -->
          <template v-else>
            <div class="preview-header">实时预览</div>
            <div v-if="isExpanding" class="expanding-hint">
              <div class="spinner" />
              <p>AI 正在创作中，请稍候...</p>
            </div>
            <!-- eslint-disable-next-line vue/no-v-html -->
            <div v-else class="preview-content" v-html="renderMarkdown(markdownText)" />
          </template>
        </div>
      </div>
    </template>

    <div v-else class="loading-placeholder">章节不存在或加载失败。</div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import {
  assistExpandChapter,
  getChapter,
  listAvailableModels,
  updateChapter,
  type ChapterResponse,
} from '@/api/product';

const props = defineProps<{ novelId: string; chapterId: string }>();

const router = useRouter();

// ─── State ─────────────────────────────────────────────────────────────────────
const tenantId = 'default';
const projectId = 'default';

const chapter = ref<ChapterResponse | null>(null);
const isLoading = ref(true);
const isSaving = ref(false);
const isExpanding = ref(false);
const isDirty = ref(false);
const errorMsg = ref('');
const successMsg = ref('');

const editTitle = ref('');
const editLang = ref('zh-CN');
const markdownText = ref('');
const aiSuggestion = ref('');

const availableModels = ref<{ id: string; name: string; endpoint: string | null }[]>([]);
const selectedModelId = ref('');
const expandMode = ref('expand');

// ─── Helpers ───────────────────────────────────────────────────────────────────
function clearNotice(): void {
  errorMsg.value = '';
  successMsg.value = '';
}

function renderMarkdown(md: string): string {
  if (!md) return '';
  const escHtml = (s: string) =>
    s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const inlineRender = (line: string) => {
    let s = escHtml(line);
    s = s.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    s = s.replace(/\*(.+?)\*/g, '<em>$1</em>');
    s = s.replace(/`(.+?)`/g, '<code>$1</code>');
    return s;
  };
  const lines = md.split('\n');
  const html: string[] = [];
  let inCode = false;
  for (const raw of lines) {
    const line = raw.trimEnd();
    if (line.startsWith('```')) {
      inCode = !inCode;
      html.push(inCode ? '<pre><code>' : '</code></pre>');
      continue;
    }
    if (inCode) { html.push(escHtml(raw) + '\n'); continue; }
    if (!line)              { html.push('<br />'); continue; }
    if (line.startsWith('### ')) { html.push(`<h3>${inlineRender(line.slice(4))}</h3>`); continue; }
    if (line.startsWith('## '))  { html.push(`<h2>${inlineRender(line.slice(3))}</h2>`); continue; }
    if (line.startsWith('# '))   { html.push(`<h1>${inlineRender(line.slice(2))}</h1>`); continue; }
    if (line.startsWith('- '))   { html.push(`<li>${inlineRender(line.slice(2))}</li>`); continue; }
    html.push(`<p>${inlineRender(line)}</p>`);
  }
  return html.join('\n');
}

const EXPAND_MODE_INSTRUCTIONS: Record<string, string> = {
  expand:   '扩写这段剧情，增加详细的场景描写、人物对话和心理活动，提升代入感。',
  complete: '补全这段剧情中的空白部分，确保情节连贯，逻辑严密。',
  rewrite:  '改写这段剧情，改变语气和表现风格，提升文学性。',
  polish:   '润色这段文本，改进措辞、语法和节奏，提升可读性。',
};

// ─── Navigation ────────────────────────────────────────────────────────────────
function goBack(): void {
  void router.push({
    name: 'studio-novel-detail',
    params: { novelId: props.novelId },
  });
}

// ─── API ───────────────────────────────────────────────────────────────────────
async function onLoad(): Promise<void> {
  isLoading.value = true;
  clearNotice();
  try {
    const [ch, models] = await Promise.all([
      getChapter(props.chapterId),
      listAvailableModels(tenantId, projectId),
    ]);
    chapter.value = ch;
    editTitle.value = ch.title ?? '';
    editLang.value = ch.language_code;
    markdownText.value = ch.markdown_text;
    availableModels.value = models;
    if (models.length > 0 && !selectedModelId.value) {
      selectedModelId.value = models[0].id;
    }
    isDirty.value = false;
  } catch (err) {
    errorMsg.value = `加载失败: ${err instanceof Error ? err.message : String(err)}`;
  } finally {
    isLoading.value = false;
  }
}

async function onSave(): Promise<void> {
  clearNotice();
  isSaving.value = true;
  try {
    await updateChapter(props.chapterId, {
      title: editTitle.value,
      language_code: editLang.value,
      markdown_text: markdownText.value,
      revision_note: '编辑器保存',
    });
    isDirty.value = false;
    successMsg.value = '已保存';
    setTimeout(() => { successMsg.value = ''; }, 2000);
  } catch (err) {
    errorMsg.value = `保存失败: ${err instanceof Error ? err.message : String(err)}`;
  } finally {
    isSaving.value = false;
  }
}

async function onAssistExpand(): Promise<void> {
  if (!selectedModelId.value) return;
  clearNotice();
  isExpanding.value = true;
  aiSuggestion.value = '';
  try {
    const result = await assistExpandChapter(props.chapterId, {
      tenant_id: tenantId,
      project_id: projectId,
      model_provider_id: selectedModelId.value,
      instruction: EXPAND_MODE_INSTRUCTIONS[expandMode.value] ?? EXPAND_MODE_INSTRUCTIONS.expand,
      style_hint: '影视化叙事，保留可分镜细节。',
      target_language: editLang.value,
      max_tokens: 900,
    });
    aiSuggestion.value = result.expanded_markdown;
  } catch (err) {
    errorMsg.value = `AI扩写失败: ${err instanceof Error ? err.message : String(err)}`;
  } finally {
    isExpanding.value = false;
  }
}

async function onAcceptExpand(): Promise<void> {
  if (!aiSuggestion.value) return;
  markdownText.value = aiSuggestion.value;
  aiSuggestion.value = '';
  isDirty.value = true;
  await onSave();
}

// ─── Lifecycle ─────────────────────────────────────────────────────────────────
onMounted(() => {
  void onLoad();
});
</script>

<style scoped>
.chapter-editor-container {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #f5f5f5;
  overflow: hidden;
}

/* ── Header ── */
.editor-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: white;
  padding: 10px 20px;
  border-bottom: 1px solid #e0e0e0;
  box-shadow: 0 2px 4px rgba(0,0,0,0.05);
  flex-shrink: 0;
  gap: 12px;
  flex-wrap: wrap;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
  min-width: 0;
}

.chapter-title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 300px;
}

.dirty-badge {
  font-size: 12px;
  color: #ff9800;
  padding: 2px 8px;
  background: #fff3e0;
  border-radius: 10px;
  border: 1px solid #ffcc80;
  white-space: nowrap;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}

/* ── Notices ── */
.notice-bar {
  padding: 8px 20px;
  font-size: 13px;
  flex-shrink: 0;
}
.notice-error   { background: #fff2f0; color: #cf1322; border-bottom: 1px solid #ffccc7; }
.notice-success { background: #f6ffed; color: #389e0d; border-bottom: 1px solid #b7eb8f; }

/* ── Meta bar ── */
.meta-bar {
  display: flex;
  align-items: center;
  gap: 20px;
  padding: 8px 20px;
  background: #fafafa;
  border-bottom: 1px solid #ebebeb;
  flex-shrink: 0;
  flex-wrap: wrap;
}

.meta-bar label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: #555;
}

.meta-input {
  padding: 4px 8px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-size: 13px;
  width: 200px;
}

.meta-select {
  padding: 4px 8px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-size: 13px;
  cursor: pointer;
}

.meta-readonly {
  font-weight: 600;
  color: #333;
}

/* ── Editor / Preview split ── */
.editor-content {
  display: grid;
  grid-template-columns: 1fr 1fr;
  flex: 1;
  overflow: hidden;
  gap: 0;
}

.editor-pane {
  display: flex;
  flex-direction: column;
  background: white;
  border-right: 1px solid #e0e0e0;
  overflow: hidden;
}

.markdown-editor {
  flex: 1;
  padding: 20px;
  border: none;
  font-family: 'Courier New', monospace;
  font-size: 14px;
  resize: none;
  outline: none;
  line-height: 1.6;
}

.preview-pane {
  display: flex;
  flex-direction: column;
  background: white;
  overflow-y: auto;
}

.preview-header {
  padding: 10px 20px;
  background: #fafafa;
  border-bottom: 1px solid #e0e0e0;
  font-weight: 600;
  font-size: 13px;
  color: #666;
  flex-shrink: 0;
}

.preview-content {
  flex: 1;
  padding: 20px;
  overflow-y: auto;
  line-height: 1.8;
  font-size: 14px;
}

.preview-content :deep(h1) { font-size: 22px; margin: 16px 0 10px; }
.preview-content :deep(h2) { font-size: 18px; margin: 14px 0 8px; }
.preview-content :deep(h3) { font-size: 15px; margin: 12px 0 6px; }
.preview-content :deep(p)  { margin-bottom: 10px; }
.preview-content :deep(li) { margin: 4px 0; }
.preview-content :deep(pre code) { background: #f3f4f6; padding: 12px; display: block; border-radius: 4px; }
.preview-content :deep(code) { background: #f3f4f6; padding: 1px 4px; border-radius: 3px; font-size: 13px; }

/* ── AI Suggestion ── */
.ai-suggestion-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow: hidden;
  border-left: 3px solid #1677ff;
}

.suggestion-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 16px;
  background: #e6f4ff;
  border-bottom: 1px solid #91caff;
  font-weight: 600;
  color: #0958d9;
  flex-shrink: 0;
  gap: 8px;
  flex-wrap: wrap;
}

.suggestion-content {
  flex: 1;
  padding: 20px;
  overflow-y: auto;
  line-height: 1.8;
  font-size: 14px;
  background: #f0f7ff;
}

.suggestion-content :deep(h1),
.suggestion-content :deep(h2),
.suggestion-content :deep(h3) { margin: 12px 0 6px; }
.suggestion-content :deep(p)  { margin-bottom: 10px; }

/* ── Loading ── */
.loading-placeholder {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #999;
  font-size: 15px;
}

.expanding-hint {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #999;
  gap: 12px;
}

.expanding-hint p { margin: 0; font-size: 14px; }

/* ── Controls ── */
.model-selector,
.expand-mode-selector {
  padding: 5px 10px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-size: 13px;
  cursor: pointer;
  background: white;
}

.btn-back {
  padding: 5px 12px;
  background: transparent;
  border: 1px solid #ddd;
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
  white-space: nowrap;
}
.btn-back:hover { background: #f0f0f0; }

.btn-ai-assistant {
  padding: 5px 14px;
  background: #52c41a;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  white-space: nowrap;
}
.btn-ai-assistant:hover:not(:disabled) { background: #389e0d; }
.btn-ai-assistant:disabled { background: #d9d9d9; cursor: not-allowed; color: #bfbfbf; }

.btn-save {
  padding: 5px 16px;
  border: 1px solid #1677ff;
  border-radius: 4px;
  cursor: pointer;
  font-size: 13px;
  color: #1677ff;
  background: white;
  white-space: nowrap;
}
.btn-save:hover:not(:disabled) { background: #e6f4ff; }
.btn-save:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-accept {
  padding: 4px 12px;
  background: #52c41a;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
}
.btn-accept:hover { background: #389e0d; }

.btn-reject {
  padding: 4px 12px;
  background: #ff4d4f;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
}
.btn-reject:hover { background: #cf1322; }

/* ── Spinner ── */
.spinner {
  border: 3px solid #f0f0f0;
  border-top: 3px solid #1677ff;
  border-radius: 50%;
  width: 32px;
  height: 32px;
  animation: spin 0.8s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

@media (max-width: 900px) {
  .editor-content { grid-template-columns: 1fr; }
  .editor-pane { min-height: 300px; border-right: none; border-bottom: 1px solid #e0e0e0; }
}
</style>
