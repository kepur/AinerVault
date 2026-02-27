<template>
  <div class="chapter-editor-container">
    <!-- 顶部工具栏 -->
    <div class="editor-header">
      <div class="header-left">
        <button class="btn-back" @click="goBack">← 返回</button>
        <h1 class="chapter-title">{{ chapter?.title || `第 ${chapter?.chapter_no} 章` }}</h1>
      </div>

      <div class="header-right">
        <!-- AI助手选项 -->
        <div class="ai-assistant-group">
          <!-- 模型选择 -->
          <select
            v-model="selectedModelId"
            class="model-selector"
            @change="onModelChanged"
          >
            <option value="" disabled>选择模型...</option>
            <option v-for="model in availableModels" :key="model.id" :value="model.id">
              {{ model.name }}{{ model.endpoint ? ` (${model.endpoint})` : '' }}
            </option>
          </select>

          <!-- 扩展模式 -->
          <select
            v-model="expandMode"
            class="expand-mode-selector"
            :disabled="!selectedModelId"
          >
            <option value="expand">扩写</option>
            <option value="complete">补全</option>
            <option value="rewrite">改写</option>
            <option value="polish">润色</option>
          </select>

          <!-- AI助手按钮 -->
          <button
            class="btn-ai-assistant"
            @click="openAIAssistantDialog"
            :disabled="!selectedModelId || !selectedText"
            title="选择文本后点击使用AI助手"
          >
            💡 AI助手
          </button>
        </div>

        <!-- 操作按钮 -->
        <button class="btn-save" @click="saveChapter">保存</button>
        <button class="btn-publish" @click="publishChapter">发布</button>
      </div>
    </div>

    <!-- 编辑区域：左编辑右预览 -->
    <div class="editor-content">
      <!-- 左侧：Markdown编辑区 -->
      <div class="editor-pane">
        <textarea
          v-model="markdownText"
          class="markdown-editor"
          placeholder="在这里写下您的故事..."
          @mouseup="updateSelectedText"
        ></textarea>
      </div>

      <!-- 右侧：实时预览区 -->
      <div class="preview-pane">
        <div class="preview-header">实时预览</div>
        <div class="preview-content" v-html="renderedPreview"></div>

        <!-- AI建议展示区 -->
        <div v-if="aiSuggestion" class="ai-suggestion-panel">
          <div class="suggestion-header">
            <span>AI建议</span>
            <button class="btn-close" @click="aiSuggestion = null">×</button>
          </div>
          <div class="suggestion-content" v-html="aiSuggestionRendered"></div>
          <div class="suggestion-actions">
            <button class="btn-accept" @click="acceptAISuggestion">接受</button>
            <button class="btn-modify" @click="openAIRefineDialog">修改</button>
            <button class="btn-reject" @click="rejectAISuggestion">拒绝</button>
          </div>
        </div>
      </div>
    </div>

    <!-- AI助手对话框 -->
    <div v-if="showAIDialog" class="modal-overlay" @click.self="closeAIAssistantDialog">
      <div class="modal-content">
        <div class="modal-header">
          <h2>AI辅助编剧</h2>
          <button class="btn-close" @click="closeAIAssistantDialog">×</button>
        </div>

        <div class="modal-body">
          <div class="form-group">
            <label>扩展模式</label>
            <select v-model="expandMode" class="form-control">
              <option value="expand">扩写 - 增加详细描写和对话</option>
              <option value="complete">补全 - 填补不完整的情节</option>
              <option value="rewrite">改写 - 改变语气或风格</option>
              <option value="polish">润色 - 改进文笔和措辞</option>
            </select>
          </div>

          <div class="form-group">
            <label>写作风格指引（可选）</label>
            <textarea
              v-model="styleGuidance"
              class="form-control"
              placeholder="例如：武侠风格、细腻深情、幽默轻松等"
              rows="3"
            ></textarea>
          </div>

          <div class="form-group">
            <label>指定指令（可选）</label>
            <textarea
              v-model="customInstruction"
              class="form-control"
              placeholder="例如：增强冲突、加快节奏、突出角色性格等"
              rows="3"
            ></textarea>
          </div>

          <div class="form-group">
            <label>输出长度限制</label>
            <input
              v-model.number="maxTokens"
              type="range"
              min="200"
              max="2500"
              step="100"
              class="form-range"
            />
            <span class="token-hint">{{ maxTokens }} tokens (约 {{ Math.floor(maxTokens * 0.25) }} 字)</span>
          </div>

          <div class="selected-text-preview">
            <label>待扩展文本预览</label>
            <div class="text-preview">{{ selectedText.substring(0, 200) }}...</div>
          </div>
        </div>

        <div class="modal-footer">
          <button class="btn-cancel" @click="closeAIAssistantDialog">取消</button>
          <button
            class="btn-generate"
            @click="generateAIExpansion"
            :disabled="isGenerating"
          >
            <span v-if="isGenerating">⏳ 生成中...</span>
            <span v-else>生成建议</span>
          </button>
        </div>
      </div>
    </div>

    <!-- 加载状态 -->
    <div v-if="isGenerating" class="loading-overlay">
      <div class="spinner"></div>
      <p>AI正在创作中，请稍候...</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()

// 章节数据
const chapter = ref<any>(null)
const markdownText = ref<string>('')
const selectedText = ref<string>('')
const originalMarkdown = ref<string>('')  // 用于取消时恢复

// AI助手状态
const selectedModelId = ref<string>('')
const availableModels = ref<any[]>([])
const expandMode = ref<string>('expand')
const styleGuidance = ref<string>('')
const customInstruction = ref<string>('')
const maxTokens = ref<number>(900)
const showAIDialog = ref<boolean>(false)
const isGenerating = ref<boolean>(false)
const aiSuggestion = ref<string | null>(null)

// 简单的 Markdown 渲染（无外部依赖）
const renderMarkdown = (text: string): string => {
  if (!text) return ''
  return text
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    .replace(/\n\n/g, '</p><p>')
    .replace(/\n/g, '<br>')
    .replace(/^(.+)$/s, '<p>$1</p>')
}

// 计算属性
const renderedPreview = computed(() => {
  return renderMarkdown(markdownText.value)
})

const aiSuggestionRendered = computed(() => {
  return renderMarkdown(aiSuggestion.value || '')
})

// 方法
const goBack = () => {
  router.back()
}

const updateSelectedText = () => {
  const textarea = document.querySelector('.markdown-editor') as HTMLTextAreaElement
  if (textarea) {
    selectedText.value = textarea.value.substring(textarea.selectionStart, textarea.selectionEnd)
  }
}

const onModelChanged = () => {
  // 模型切换时的回调
  console.log('Model changed:', selectedModelId.value)
}

const openAIAssistantDialog = () => {
  if (!selectedModelId.value) {
    alert('请先从下拉框选择一个模型')
    return
  }
  if (!selectedText.value) {
    alert('请先在编辑区选中要扩展的文本')
    return
  }
  showAIDialog.value = true
}

const closeAIAssistantDialog = () => {
  showAIDialog.value = false
  // 取消时，如果AI建议还未被接受，则保持当前编辑内容
  // 如果要恢复原始内容，可以添加：markdownText.value = originalMarkdown.value
}

const generateAIExpansion = async () => {
  if (!selectedModelId.value || !selectedText.value) {
    alert('请选择模型并选中文本')
    return
  }

  isGenerating.value = true
  try {
    const response = await fetch(
      `/api/v1/chapters/${route.params.chapterId}/ai-expand`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          tenant_id: 'default-tenant',
          project_id: 'default-project',
          model_provider_id: selectedModelId.value,  // 传递用户选择的模型ID
          instruction: customInstruction.value || getDefaultInstruction(expandMode.value),
          style_hint: styleGuidance.value || '影视化叙事，保留可分镜细节。',
          target_language: 'zh',
          max_tokens: maxTokens.value,
        }),
      }
    )

    if (!response.ok) {
      const errorData = await response.json()
      throw new Error(errorData.detail || 'AI生成失败')
    }

    const data = await response.json()
    aiSuggestion.value = data.expanded_markdown
    showAIDialog.value = false  // 自动关闭对话框，显示建议
  } catch (error) {
    alert('AI生成出错: ' + error)
  } finally {
    isGenerating.value = false
  }
}

const acceptAISuggestion = async () => {
  if (aiSuggestion.value) {
    const textarea = document.querySelector('.markdown-editor') as HTMLTextAreaElement
    const start = textarea.selectionStart
    const end = textarea.selectionEnd
    const before = markdownText.value.substring(0, start)
    const after = markdownText.value.substring(end)
    markdownText.value = before + aiSuggestion.value + after
    aiSuggestion.value = null

    // 自动保存（可选，取决于用户需求）
    // 这里暂不自动保存，让用户点击保存按钮
  }
}

const openAIRefineDialog = () => {
  // 打开细化对话框
  showAIDialog.value = true
}

const rejectAISuggestion = () => {
  aiSuggestion.value = null
}

const saveChapter = async () => {
  try {
    const response = await fetch(
      `/api/v1/novels/${route.params.novelId}/chapters/${route.params.chapterId}`,
      {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          title: chapter.value?.title,
          markdown_text: markdownText.value,
          revision_note: '编辑器保存',
        }),
      }
    )

    if (!response.ok) {
      throw new Error('保存失败')
    }

    alert('章节已保存')
  } catch (error) {
    alert('保存出错: ' + error)
  }
}

const publishChapter = async () => {
  try {
    const response = await fetch(
      `/api/v1/chapters/${route.params.chapterId}/publish-approval`,
      {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          tenant_id: 'default-tenant',
          project_id: 'default-project',
          action: 'submit',
        }),
      }
    )

    if (!response.ok) {
      throw new Error('发布失败')
    }

    alert('章节已提交审批')
  } catch (error) {
    alert('发布出错: ' + error)
  }
}

const getDefaultInstruction = (mode: string): string => {
  const instructions: Record<string, string> = {
    expand: '扩写这段剧情，增加详细的场景描写、人物对话和心理活动，提升代入感。',
    complete: '补全这段剧情中的空白部分，确保情节连贯，逻辑严密。',
    rewrite: '改写这段剧情，改变语气和表现风格，提升文学性。',
    polish: '润色这段文本，改进措辞、语法和节奏，提升可读性。',
  }
  return instructions[mode] || ''
}

// 生命周期
onMounted(async () => {
  // 加载章节数据
  try {
    const response = await fetch(
      `/api/v1/novels/${route.params.novelId}/chapters/${route.params.chapterId}`
    )
    if (response.ok) {
      chapter.value = await response.json()
      markdownText.value = chapter.value.markdown_text || ''
      originalMarkdown.value = markdownText.value  // 保存原始内容用于恢复
    }
  } catch (error) {
    console.error('加载章节失败:', error)
  }

  // 加载可用的模型列表
  try {
    const modelsResponse = await fetch(
      `/api/v1/chapters/available-models?tenant_id=default-tenant&project_id=default-project`
    )
    if (modelsResponse.ok) {
      availableModels.value = await modelsResponse.json()
      // 自动选择第一个模型
      if (availableModels.value.length > 0) {
        selectedModelId.value = availableModels.value[0].id
      }
    }
  } catch (error) {
    console.error('加载模型列表失败:', error)
  }
})
</script>

<style scoped>
.chapter-editor-container {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #f5f5f5;
}

.editor-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: white;
  padding: 12px 20px;
  border-bottom: 1px solid #e0e0e0;
  box-shadow: 0 2px 4px rgba(0, 0, 0, 0.05);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 12px;
}

.btn-back {
  padding: 6px 12px;
  background: transparent;
  border: 1px solid #ddd;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
}

.btn-back:hover {
  background: #f0f0f0;
}

.chapter-title {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 12px;
}

.ai-assistant-group {
  display: flex;
  gap: 8px;
  align-items: center;
}

.model-selector,
.expand-mode-selector {
  padding: 6px 12px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-size: 14px;
  cursor: pointer;
  background: white;
}

.model-selector:hover,
.expand-mode-selector:hover {
  border-color: #999;
}

.btn-ai-assistant {
  padding: 6px 16px;
  background: #4CAF50;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
  transition: all 0.3s;
}

.btn-ai-assistant:hover:not(:disabled) {
  background: #45a049;
  box-shadow: 0 2px 8px rgba(76, 175, 80, 0.3);
}

.btn-ai-assistant:disabled {
  background: #ccc;
  cursor: not-allowed;
  opacity: 0.6;
}

.btn-save,
.btn-publish {
  padding: 6px 16px;
  border: 1px solid #ddd;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
  background: white;
  transition: all 0.3s;
}

.btn-save:hover {
  border-color: #2196F3;
  color: #2196F3;
}

.btn-publish:hover {
  border-color: #ff9800;
  color: #ff9800;
}

.editor-content {
  display: flex;
  flex: 1;
  gap: 0;
  overflow: hidden;
}

.editor-pane {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: white;
  border-right: 1px solid #e0e0e0;
}

.markdown-editor {
  flex: 1;
  padding: 20px;
  border: none;
  font-family: 'Courier New', monospace;
  font-size: 14px;
  resize: none;
  outline: none;
}

.preview-pane {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: white;
  overflow-y: auto;
}

.preview-header {
  padding: 12px 20px;
  background: #fafafa;
  border-bottom: 1px solid #e0e0e0;
  font-weight: 600;
  font-size: 14px;
}

.preview-content {
  flex: 1;
  padding: 20px;
  overflow-y: auto;
  line-height: 1.8;
}

.preview-content :deep(h1) {
  font-size: 24px;
  margin-top: 16px;
  margin-bottom: 12px;
}

.preview-content :deep(p) {
  margin-bottom: 12px;
}

.ai-suggestion-panel {
  background: #e8f5e9;
  border-top: 2px solid #4CAF50;
  padding: 12px;
  margin-top: 12px;
}

.suggestion-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  font-weight: 600;
  color: #2e7d32;
}

.btn-close {
  background: transparent;
  border: none;
  cursor: pointer;
  font-size: 20px;
  color: #666;
}

.suggestion-content {
  padding: 12px;
  background: white;
  border-radius: 4px;
  margin-bottom: 12px;
  max-height: 200px;
  overflow-y: auto;
  line-height: 1.6;
}

.suggestion-actions {
  display: flex;
  gap: 8px;
  justify-content: flex-end;
}

.btn-accept,
.btn-modify,
.btn-reject {
  padding: 6px 12px;
  border: 1px solid #ddd;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
  transition: all 0.3s;
}

.btn-accept {
  background: #4CAF50;
  color: white;
  border: none;
}

.btn-accept:hover {
  background: #45a049;
}

.btn-modify {
  background: #2196F3;
  color: white;
  border: none;
}

.btn-modify:hover {
  background: #0b7dda;
}

.btn-reject {
  background: #f44336;
  color: white;
  border: none;
}

.btn-reject:hover {
  background: #da190b;
}

/* 模态框样式 */
.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
}

.modal-content {
  background: white;
  border-radius: 8px;
  width: 90%;
  max-width: 500px;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 20px;
  border-bottom: 1px solid #e0e0e0;
}

.modal-header h2 {
  margin: 0;
  font-size: 18px;
}

.modal-body {
  flex: 1;
  padding: 20px;
  overflow-y: auto;
}

.form-group {
  margin-bottom: 16px;
}

.form-group label {
  display: block;
  margin-bottom: 8px;
  font-weight: 600;
  font-size: 14px;
}

.form-control {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-size: 14px;
  font-family: inherit;
  resize: vertical;
}

.form-control:focus {
  outline: none;
  border-color: #4CAF50;
  box-shadow: 0 0 0 3px rgba(76, 175, 80, 0.1);
}

.form-range {
  width: 100%;
  height: 6px;
  cursor: pointer;
}

.token-hint {
  display: block;
  margin-top: 6px;
  font-size: 12px;
  color: #666;
}

.selected-text-preview {
  margin-top: 16px;
  padding: 12px;
  background: #f5f5f5;
  border-radius: 4px;
}

.text-preview {
  margin-top: 8px;
  padding: 8px;
  background: white;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-size: 13px;
  color: #666;
  max-height: 80px;
  overflow-y: auto;
  line-height: 1.5;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
  padding: 16px 20px;
  border-top: 1px solid #e0e0e0;
}

.btn-cancel {
  padding: 8px 16px;
  background: white;
  border: 1px solid #ddd;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.3s;
}

.btn-cancel:hover {
  border-color: #999;
  background: #f9f9f9;
}

.btn-generate {
  padding: 8px 20px;
  background: #4CAF50;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 600;
  transition: all 0.3s;
}

.btn-generate:hover:not(:disabled) {
  background: #45a049;
  box-shadow: 0 2px 8px rgba(76, 175, 80, 0.3);
}

.btn-generate:disabled {
  background: #ccc;
  cursor: not-allowed;
  opacity: 0.6;
}

/* 加载状态 */
.loading-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.7);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  z-index: 2000;
}

.spinner {
  border: 4px solid rgba(255, 255, 255, 0.3);
  border-top: 4px solid white;
  border-radius: 50%;
  width: 50px;
  height: 50px;
  animation: spin 1s linear infinite;
}

@keyframes spin {
  0% {
    transform: rotate(0deg);
  }
  100% {
    transform: rotate(360deg);
  }
}

.loading-overlay p {
  color: white;
  margin-top: 16px;
  font-size: 16px;
}
</style>
