<template>
  <div class="revision-container">
    <!-- 顶部导航 -->
    <div class="page-header">
      <button class="btn-back" @click="goBack">← 返回</button>
      <h1>📜 章节修订历史</h1>
      <p class="subtitle">{{ chapterTitle }}</p>
    </div>

    <!-- 加载状态 -->
    <div v-if="isLoading" class="loading">
      <div class="spinner"></div>
      <p>加载修订历史...</p>
    </div>

    <!-- 修订列表 -->
    <div v-else-if="revisions.length > 0" class="revisions-list">
      <div v-for="(revision, index) in revisions" :key="revision.revision_id" class="revision-item">
        <!-- 修订头部 -->
        <div class="revision-header" @click="toggleRevision(revision.revision_id)">
          <div class="revision-info">
            <span class="revision-number">修订 {{ index + 1 }}</span>
            <span class="revision-date">{{ formatTime(revision.occurred_at) }}</span>
            <span v-if="revision.editor" class="revision-editor">编辑者: {{ revision.editor }}</span>
          </div>
          <div class="revision-note">
            {{ revision.note || '(无备注)' }}
          </div>
          <button class="btn-expand">{{ expandedRevisions[revision.revision_id] ? '▼' : '▶' }}</button>
        </div>

        <!-- 修订详情（展开）-->
        <div v-show="expandedRevisions[revision.revision_id]" class="revision-detail">
          <div class="detail-stats">
            <span class="stat">字数: {{ revision.previous_markdown_text?.length || 0 }}</span>
            <span class="stat">段落数: {{ revision.previous_markdown_text?.split('\n').length || 0 }}</span>
          </div>

          <div class="detail-content">
            <h4>修订前内容：</h4>
            <div class="text-preview">{{ revision.previous_markdown_text?.substring(0, 300) }}...</div>
          </div>

          <div class="detail-actions">
            <button class="btn-view" @click="viewFullRevision(revision.revision_id)">
              📄 查看完整内容
            </button>
            <button class="btn-compare" @click="compareWithCurrent(revision.revision_id)">
              🔄 与当前版本对比
            </button>
            <button class="btn-restore" @click="restoreRevision(revision.revision_id)">
              ↩️ 恢复此版本
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- 无修订 -->
    <div v-else class="empty-state">
      <p>📭 该章节暂无修订历史</p>
    </div>

    <!-- 对比模态框 -->
    <div v-if="showCompareModal" class="modal-overlay" @click.self="showCompareModal = false">
      <div class="modal-content large">
        <div class="modal-header">
          <h2>版本对比</h2>
          <button class="btn-close" @click="showCompareModal = false">×</button>
        </div>

        <div class="modal-body">
          <div class="compare-container">
            <!-- 左侧：历史版本 -->
            <div class="compare-pane">
              <h4>历史版本</h4>
              <div class="text-content">{{ compareData.oldText?.substring(0, 500) }}</div>
            </div>

            <!-- 分隔线 -->
            <div class="compare-divider"></div>

            <!-- 右侧：当前版本 -->
            <div class="compare-pane">
              <h4>当前版本</h4>
              <div class="text-content">{{ compareData.newText?.substring(0, 500) }}</div>
            </div>
          </div>
        </div>

        <div class="modal-footer">
          <button class="btn-cancel" @click="showCompareModal = false">关闭</button>
        </div>
      </div>
    </div>

    <!-- 完整内容模态框 -->
    <div v-if="showDetailModal" class="modal-overlay" @click.self="showDetailModal = false">
      <div class="modal-content">
        <div class="modal-header">
          <h2>修订内容详情</h2>
          <button class="btn-close" @click="showDetailModal = false">×</button>
        </div>

        <div class="modal-body">
          <div class="full-content">{{ detailContent }}</div>
        </div>

        <div class="modal-footer">
          <button class="btn-cancel" @click="showDetailModal = false">关闭</button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'

interface Revision {
  revision_id: string
  occurred_at: string
  chapter_id: string
  note: string | null
  editor: string | null
  previous_markdown_text: string
}

import { useI18n } from "@/composables/useI18n";

const { t } = useI18n();

const route = useRoute()
const router = useRouter()

const revisions = ref<Revision[]>([])
const isLoading = ref(false)
const chapterTitle = ref<string>('')
const expandedRevisions = ref<Record<string, boolean>>({})
const showCompareModal = ref(false)
const showDetailModal = ref(false)
const detailContent = ref<string>('')
const compareData = ref<{ oldText: string; newText: string }>({
  oldText: '',
  newText: '',
})

const goBack = () => {
  router.back()
}

const loadRevisions = async () => {
  isLoading.value = true
  try {
    const chapterId = route.params.chapterId as string

    // 加载修订历史
    const response = await fetch(`/api/v1/chapters/${chapterId}/revisions`)
    if (response.ok) {
      revisions.value = await response.json()
    }

    // 加载章节信息获取标题
    const novelId = route.params.novelId as string
    const chapterResponse = await fetch(
      `/api/v1/novels/${novelId}/chapters/${chapterId}`
    )
    if (chapterResponse.ok) {
      const chapter = await chapterResponse.json()
      chapterTitle.value = chapter.title || `第 ${chapter.chapter_no} 章`
    }
  } catch (error) {
    console.error('加载修订历史失败:', error)
    alert('加载修订历史失败')
  } finally {
    isLoading.value = false
  }
}

const formatTime = (dateStr: string): string => {
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN')
}

const toggleRevision = (revisionId: string) => {
  expandedRevisions.value[revisionId] = !expandedRevisions.value[revisionId]
}

const viewFullRevision = (revisionId: string) => {
  const revision = revisions.value.find(r => r.revision_id === revisionId)
  if (revision) {
    detailContent.value = revision.previous_markdown_text
    showDetailModal.value = true
  }
}

const compareWithCurrent = async (revisionId: string) => {
  const revision = revisions.value.find(r => r.revision_id === revisionId)
  if (!revision) return

  try {
    const chapterId = route.params.chapterId as string
    const novelId = route.params.novelId as string

    const response = await fetch(
      `/api/v1/novels/${novelId}/chapters/${chapterId}`
    )
    if (response.ok) {
      const current = await response.json()
      compareData.value = {
        oldText: revision.previous_markdown_text,
        newText: current.markdown_text || '',
      }
      showCompareModal.value = true
    }
  } catch (error) {
    console.error('加载对比失败:', error)
    alert('加载对比失败')
  }
}

const restoreRevision = async (revisionId: string) => {
  const revision = revisions.value.find(r => r.revision_id === revisionId)
  if (!revision) return

  if (!confirm('确认要恢复此版本吗？当前版本将被覆盖。')) {
    return
  }

  try {
    const chapterId = route.params.chapterId as string
    const novelId = route.params.novelId as string

    const response = await fetch(
      `/api/v1/novels/${novelId}/chapters/${chapterId}`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          markdown_text: revision.previous_markdown_text,
          revision_note: `从修订 ${revisionId} 恢复`,
        }),
      }
    )

    if (response.ok) {
      alert('版本已恢复')
      loadRevisions()
    }
  } catch (error) {
    console.error('恢复版本失败:', error)
    alert('恢复版本失败')
  }
}

onMounted(() => {
  loadRevisions()
})
</script>

<style scoped>
.revision-container {
  padding: 20px;
  background: #f5f5f5;
  min-height: 100vh;
}

.page-header {
  margin-bottom: 30px;
}

.btn-back {
  background: none;
  border: none;
  font-size: 16px;
  cursor: pointer;
  color: #4CAF50;
  margin-bottom: 10px;
}

.page-header h1 {
  font-size: 28px;
  margin: 10px 0 0;
  color: #333;
}

.subtitle {
  color: #666;
  margin-top: 5px;
  font-size: 14px;
}

.loading {
  text-align: center;
  padding: 40px;
}

.spinner {
  width: 40px;
  height: 40px;
  border: 4px solid #f3f3f3;
  border-top: 4px solid #4CAF50;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin: 0 auto 15px;
}

@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

.revisions-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.revision-item {
  background: white;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
  transition: box-shadow 0.2s;
}

.revision-item:hover {
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.15);
}

.revision-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px;
  background: #fafafa;
  border-bottom: 1px solid #eee;
  cursor: pointer;
  transition: background 0.2s;
}

.revision-header:hover {
  background: #f0f0f0;
}

.revision-info {
  display: flex;
  gap: 16px;
  align-items: center;
  flex: 1;
}

.revision-number {
  font-weight: 600;
  color: #333;
}

.revision-date {
  color: #666;
  font-size: 12px;
  font-family: monospace;
}

.revision-editor {
  color: #999;
  font-size: 12px;
}

.revision-note {
  flex: 1;
  color: #666;
  font-size: 14px;
  padding: 0 16px;
}

.btn-expand {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 14px;
  color: #4CAF50;
  padding: 4px 8px;
}

.revision-detail {
  padding: 16px;
  background: #fafafa;
  border-top: 1px solid #eee;
}

.detail-stats {
  display: flex;
  gap: 20px;
  margin-bottom: 16px;
}

.stat {
  color: #666;
  font-size: 12px;
}

.detail-content {
  margin: 16px 0;
}

.detail-content h4 {
  margin: 0 0 8px 0;
  color: #333;
  font-size: 14px;
}

.text-preview {
  background: white;
  padding: 12px;
  border-radius: 4px;
  color: #666;
  font-size: 13px;
  line-height: 1.5;
  border-left: 3px solid #4CAF50;
}

.detail-actions {
  display: flex;
  gap: 8px;
  margin-top: 16px;
}

.btn-view,
.btn-compare,
.btn-restore {
  padding: 8px 12px;
  border: 1px solid #ddd;
  border-radius: 4px;
  background: white;
  color: #666;
  cursor: pointer;
  font-size: 12px;
  transition: all 0.2s;
}

.btn-view:hover,
.btn-compare:hover {
  border-color: #4CAF50;
  color: #4CAF50;
}

.btn-restore:hover {
  border-color: #ff9800;
  color: #ff9800;
}

.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: #999;
}

.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  justify-content: center;
  align-items: center;
  z-index: 1000;
}

.modal-content {
  background: white;
  border-radius: 8px;
  max-width: 600px;
  width: 90%;
  max-height: 80vh;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}

.modal-content.large {
  max-width: 1000px;
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px;
  border-bottom: 1px solid #eee;
}

.modal-header h2 {
  margin: 0;
  font-size: 18px;
  color: #333;
}

.btn-close {
  background: none;
  border: none;
  font-size: 24px;
  cursor: pointer;
  color: #999;
}

.modal-body {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
}

.compare-container {
  display: flex;
  gap: 16px;
  min-height: 400px;
}

.compare-pane {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.compare-pane h4 {
  margin: 0 0 12px 0;
  color: #333;
  font-size: 14px;
}

.compare-divider {
  width: 2px;
  background: #ddd;
}

.text-content {
  flex: 1;
  background: #f5f5f5;
  padding: 12px;
  border-radius: 4px;
  overflow-y: auto;
  font-size: 12px;
  line-height: 1.6;
  color: #666;
  font-family: monospace;
  white-space: pre-wrap;
  word-break: break-word;
}

.full-content {
  background: #f5f5f5;
  padding: 16px;
  border-radius: 4px;
  font-size: 13px;
  line-height: 1.8;
  color: #666;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 60vh;
  overflow-y: auto;
}

.modal-footer {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  padding: 16px;
  border-top: 1px solid #eee;
}

.btn-cancel {
  padding: 8px 16px;
  background: white;
  border: 1px solid #ddd;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.2s;
}

.btn-cancel:hover {
  border-color: #999;
  background: #f5f5f5;
}
</style>
