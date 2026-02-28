<template>
  <div class="preview-container">
    <!-- 顶部导航 -->
    <div class="page-header">
      <button class="btn-back" @click="goBack">← 返回编辑器</button>
      <h1>🔍 章节内容预览与规划</h1>
      <p class="subtitle">SKILL 01/02/03 预处理结果预览</p>
    </div>

    <!-- 配置面板 -->
    <div class="config-panel">
      <div class="config-section">
        <h3>预览配置</h3>

        <div class="form-group">
          <label>目标语言:</label>
          <input
            v-model="previewConfig.target_output_language"
            type="text"
            placeholder="zh, en, ja 等"
            class="input-field"
          />
        </div>

        <div class="form-group">
          <label>地区/方言:</label>
          <input
            v-model="previewConfig.target_locale"
            type="text"
            placeholder="zh-CN, en-US 等"
            class="input-field"
          />
        </div>

        <div class="form-group">
          <label>故事类型:</label>
          <input
            v-model="previewConfig.genre"
            type="text"
            placeholder="例: 武侠、科幻、恐怖等"
            class="input-field"
          />
        </div>

        <div class="form-group">
          <label>故事世界观:</label>
          <textarea
            v-model="previewConfig.story_world_setting"
            placeholder="例: 架空历史，现代都市等"
            class="textarea-field"
            rows="3"
          ></textarea>
        </div>

        <div class="form-group">
          <label>文化包ID (可选):</label>
          <input
            v-model="previewConfig.culture_pack_id"
            type="text"
            placeholder="cp_xxx"
            class="input-field"
          />
        </div>

        <div class="form-group">
          <label>Persona参考 (可选):</label>
          <input
            v-model="previewConfig.persona_ref"
            type="text"
            placeholder="persona_xxx"
            class="input-field"
          />
        </div>

        <button class="btn-preview" @click="generatePreview" :disabled="isLoading">
          <span v-if="isLoading">⏳ 生成中...</span>
          <span v-else>🎬 生成预览</span>
        </button>
      </div>
    </div>

    <!-- 加载状态 -->
    <div v-if="isLoading" class="loading">
      <div class="spinner"></div>
      <p>正在分析章节内容...</p>
      <p class="loading-hint">此过程涉及多个SKILL模块的处理</p>
    </div>

    <!-- 预览结果 -->
    <div v-else-if="previewResult" class="preview-result">
      <!-- SKILL_01: 规范化 -->
      <div class="result-section">
        <h3>📝 SKILL_01 内容规范化</h3>
        <div class="result-card">
          <div class="status-badge" :class="`status-${previewResult.skill_01_status}`">
            {{ getStatusText(previewResult.skill_01_status) }}
          </div>
          <p>规范化后的文本 (前500字):</p>
          <div class="text-preview">{{ previewResult.normalized_text?.substring(0, 500) }}</div>
        </div>
      </div>

      <!-- SKILL_02: 语言路由 -->
      <div class="result-section">
        <h3>🌍 SKILL_02 语言上下文路由</h3>
        <div class="result-card">
          <div class="status-badge" :class="`status-${previewResult.skill_02_status}`">
            {{ getStatusText(previewResult.skill_02_status) }}
          </div>
          <p>目标语言: {{ previewConfig.target_output_language || 'zh (默认)' }}</p>
          <p>地区/方言: {{ previewConfig.target_locale || '自动检测' }}</p>
          <p class="hint">此模块处理语言特定的上下文和方言适配</p>
        </div>
      </div>

      <!-- SKILL_03: 场景规划 -->
      <div class="result-section">
        <h3>🎬 SKILL_03 场景和镜头规划</h3>
        <div class="result-card">
          <div class="status-badge" :class="`status-${previewResult.skill_03_status}`">
            {{ getStatusText(previewResult.skill_03_status) }}
          </div>

          <div class="stats">
            <div class="stat-item">
              <span class="stat-label">检测到的场景数:</span>
              <span class="stat-value">{{ previewResult.scene_count || 0 }}</span>
            </div>
            <div class="stat-item">
              <span class="stat-label">检测到的镜头数:</span>
              <span class="stat-value">{{ previewResult.shot_count || 0 }}</span>
            </div>
          </div>

          <!-- 场景列表 -->
          <div v-if="previewResult.scene_plan && previewResult.scene_plan.length > 0">
            <h4>场景列表:</h4>
            <div class="plan-list">
              <div v-for="(scene, idx) in previewResult.scene_plan" :key="`scene-${idx}`" class="plan-item">
                <span class="plan-number">场景 {{ idx + 1 }}</span>
                <span class="plan-text">{{ scene.description || scene.title || '(无描述)' }}</span>
              </div>
            </div>
          </div>

          <!-- 镜头列表 -->
          <div v-if="previewResult.shot_plan && previewResult.shot_plan.length > 0">
            <h4>镜头列表:</h4>
            <div class="plan-list">
              <div v-for="(shot, idx) in previewResult.shot_plan" :key="`shot-${idx}`" class="plan-item">
                <span class="plan-number">镜头 {{ idx + 1 }}</span>
                <span class="plan-text">{{ shot.description || shot.shot_type || '(无描述)' }}</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- 文化参考 -->
      <div class="result-section">
        <h3>🎭 建议的文化包</h3>
        <div class="result-card">
          <div v-if="previewResult.culture_candidates && previewResult.culture_candidates.length > 0">
            <p>根据内容分析，推荐以下文化包:</p>
            <div class="culture-list">
              <div v-for="(culture, idx) in previewResult.culture_candidates" :key="`culture-${idx}`" class="culture-item">
                🎨 {{ culture }}
              </div>
            </div>
          </div>
          <div v-else>
            <p class="hint">未检测到特定的文化参考需求</p>
          </div>
        </div>
      </div>

      <!-- 操作按钮 -->
      <div class="actions">
        <button class="btn-generate-new" @click="previewResult = null">
          🔄 生成其他配置预览
        </button>
        <button class="btn-export" @click="exportPreview">
          📥 导出预览结果
        </button>
      </div>
    </div>

    <!-- 空状态 -->
    <div v-else class="empty-state">
      <p>📭 请配置参数并点击"生成预览"按钮</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, reactive } from 'vue'
import { useRoute, useRouter } from 'vue-router'

interface PreviewConfig {
  target_output_language: string
  target_locale: string
  genre: string
  story_world_setting: string
  culture_pack_id: string | null
  persona_ref: string | null
}

interface PreviewResult {
  preview_run_id: string
  skill_01_status: string
  skill_02_status: string
  skill_03_status: string
  normalized_text: string
  culture_candidates: string[]
  scene_count: number
  shot_count: number
  scene_plan: Array<{ description?: string; title?: string }>
  shot_plan: Array<{ description?: string; shot_type?: string }>
}

import { useI18n } from "@/composables/useI18n";

const { t } = useI18n();

const route = useRoute()
const router = useRouter()

const previewConfig = reactive<PreviewConfig>({
  target_output_language: 'zh',
  target_locale: '',
  genre: '',
  story_world_setting: '',
  culture_pack_id: null,
  persona_ref: null,
})

const previewResult = ref<PreviewResult | null>(null)
const isLoading = ref(false)

const goBack = () => {
  router.back()
}

const generatePreview = async () => {
  isLoading.value = true
  try {
    const chapterId = route.params.chapterId as string

    const response = await fetch(`/api/v1/chapters/${chapterId}/preview-plan`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        tenant_id: 'default-tenant',
        project_id: 'default-project',
        target_output_language: previewConfig.target_output_language || undefined,
        target_locale: previewConfig.target_locale || undefined,
        genre: previewConfig.genre || '',
        story_world_setting: previewConfig.story_world_setting || '',
        culture_pack_id: previewConfig.culture_pack_id || undefined,
        persona_ref: previewConfig.persona_ref || undefined,
      }),
    })

    if (response.ok) {
      previewResult.value = await response.json()
    } else {
      alert('生成预览失败')
    }
  } catch (error) {
    console.error('生成预览失败:', error)
    alert('生成预览失败')
  } finally {
    isLoading.value = false
  }
}

const getStatusText = (status: string): string => {
  const texts: Record<string, string> = {
    success: '✅ 成功',
    processing: '⏳ 处理中',
    failed: '❌ 失败',
    pending: '⏹ 待处理',
  }
  return texts[status] || `❓ ${status}`
}

const exportPreview = () => {
  if (!previewResult.value) return
  const data = JSON.stringify(previewResult.value, null, 2)
  const blob = new Blob([data], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `preview_${Date.now()}.json`
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<style scoped>
.preview-container {
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

.config-panel {
  background: white;
  border-radius: 8px;
  padding: 20px;
  margin-bottom: 20px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.config-section h3 {
  margin: 0 0 16px 0;
  color: #333;
  font-size: 16px;
}

.form-group {
  margin-bottom: 16px;
}

.form-group label {
  display: block;
  color: #555;
  font-size: 14px;
  margin-bottom: 6px;
  font-weight: 500;
}

.input-field,
.textarea-field {
  width: 100%;
  padding: 8px 12px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-size: 14px;
  font-family: inherit;
}

.input-field:focus,
.textarea-field:focus {
  outline: none;
  border-color: #4CAF50;
  background-color: #f9fff9;
}

.textarea-field {
  resize: vertical;
}

.btn-preview {
  padding: 10px 20px;
  background: #4CAF50;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
  transition: background 0.2s;
}

.btn-preview:hover:not(:disabled) {
  background: #45a049;
}

.btn-preview:disabled {
  background: #ccc;
  cursor: not-allowed;
}

.loading {
  text-align: center;
  padding: 60px 20px;
}

.spinner {
  width: 50px;
  height: 50px;
  border: 4px solid #f3f3f3;
  border-top: 4px solid #4CAF50;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin: 0 auto 20px;
}

@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

.loading-hint {
  color: #999;
  font-size: 12px;
  margin-top: 10px;
}

.preview-result {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.result-section {
  background: white;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.result-section h3 {
  margin: 0;
  padding: 16px;
  background: #f5f5f5;
  border-bottom: 1px solid #eee;
  color: #333;
  font-size: 16px;
}

.result-card {
  padding: 16px;
}

.status-badge {
  display: inline-block;
  padding: 4px 12px;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 500;
  margin-bottom: 12px;
}

.status-success {
  background: #d4edda;
  color: #155724;
}

.status-processing {
  background: #fff3cd;
  color: #856404;
}

.status-failed {
  background: #f8d7da;
  color: #721c24;
}

.status-pending {
  background: #e2e3e5;
  color: #383d41;
}

.result-card p {
  color: #666;
  font-size: 14px;
  margin: 12px 0;
}

.hint {
  color: #999;
  font-size: 12px;
}

.text-preview {
  background: #f9f9f9;
  padding: 12px;
  border-radius: 4px;
  border-left: 3px solid #4CAF50;
  font-size: 13px;
  line-height: 1.6;
  color: #666;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 300px;
  overflow-y: auto;
}

.stats {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 16px;
  margin: 16px 0;
}

.stat-item {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px;
  background: #f5f5f5;
  border-radius: 4px;
}

.stat-label {
  color: #666;
  font-size: 12px;
}

.stat-value {
  color: #4CAF50;
  font-size: 24px;
  font-weight: 600;
}

.result-card h4 {
  margin: 16px 0 8px 0;
  color: #333;
  font-size: 14px;
}

.plan-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.plan-item {
  display: flex;
  gap: 12px;
  padding: 8px 12px;
  background: #f9f9f9;
  border-radius: 4px;
  font-size: 13px;
}

.plan-number {
  color: #4CAF50;
  font-weight: 500;
  min-width: 60px;
}

.plan-text {
  color: #666;
  flex: 1;
}

.culture-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-top: 12px;
}

.culture-item {
  padding: 8px 12px;
  background: #f0f8ff;
  border-left: 3px solid #4CAF50;
  border-radius: 4px;
  font-size: 13px;
  color: #333;
}

.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: #999;
}

.actions {
  display: flex;
  gap: 8px;
  padding: 20px;
  background: white;
  border-radius: 8px;
  justify-content: flex-start;
}

.btn-generate-new,
.btn-export {
  padding: 8px 16px;
  background: white;
  border: 1px solid #ddd;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.2s;
}

.btn-generate-new:hover,
.btn-export:hover {
  border-color: #4CAF50;
  color: #4CAF50;
}
</style>
