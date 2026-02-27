<template>
  <div class="snapshot-container">
    <!-- 顶部导航 -->
    <div class="page-header">
      <button class="btn-back" @click="goBack">← 返回</button>
      <h1>📸 运行配置快照</h1>
      <p class="subtitle">查看任务执行时的配置状态</p>
    </div>

    <!-- 快照选择 -->
    <div class="run-selector">
      <label>选择运行 (Run):</label>
      <input
        v-model="runId"
        type="text"
        placeholder="输入Run ID"
        class="input-field"
        @keyup.enter="loadSnapshot"
      />
      <button class="btn-load" @click="loadSnapshot">🔍 加载</button>
    </div>

    <!-- 加载状态 -->
    <div v-if="isLoading" class="loading">
      <div class="spinner"></div>
      <p>加载快照...</p>
    </div>

    <!-- 快照内容 -->
    <div v-else-if="snapshot" class="snapshot-content">
      <!-- 快照基本信息 -->
      <div class="snapshot-info">
        <div class="info-row">
          <span class="label">运行ID:</span>
          <span class="value">{{ runId }}</span>
        </div>
        <div class="info-row">
          <span class="label">快照时间:</span>
          <span class="value">{{ formatTime(snapshot.created_at) }}</span>
        </div>
        <div class="info-row">
          <span class="label">快照状态:</span>
          <span class="value badge">{{ snapshot.status || 'active' }}</span>
        </div>
      </div>

      <!-- 标签页切换 -->
      <div class="tabs">
        <button
          v-for="tab in tabs"
          :key="tab"
          class="tab"
          :class="{ active: activeTab === tab }"
          @click="activeTab = tab"
        >
          {{ tabLabels[tab] }}
        </button>
      </div>

      <!-- 标签页内容 -->
      <div class="tab-content">
        <!-- 模型配置 -->
        <div v-if="activeTab === 'models'" class="config-section">
          <h3>模型配置 (ModelProfile)</h3>
          <div class="config-item">
            <div class="config-header">
              <span class="config-name">模型档案</span>
              <button class="btn-expand" @click="toggleExpand('models')">
                {{ expanded.models ? '▼' : '▶' }}
              </button>
            </div>
            <pre v-show="expanded.models" class="config-value">{{
              formatJson(snapshot.model_profiles)
            }}</pre>
          </div>
        </div>

        <!-- Provider配置 -->
        <div v-if="activeTab === 'providers'" class="config-section">
          <h3>Provider配置</h3>
          <div class="config-item">
            <div class="config-header">
              <span class="config-name">API提供商</span>
              <button class="btn-expand" @click="toggleExpand('providers')">
                {{ expanded.providers ? '▼' : '▶' }}
              </button>
            </div>
            <pre v-show="expanded.providers" class="config-value">{{
              formatJson(snapshot.providers)
            }}</pre>
          </div>
        </div>

        <!-- 路由配置 -->
        <div v-if="activeTab === 'routing'" class="config-section">
          <h3>路由配置 (FeatureRoute)</h3>
          <div class="config-item">
            <div class="config-header">
              <span class="config-name">功能路由</span>
              <button class="btn-expand" @click="toggleExpand('routing')">
                {{ expanded.routing ? '▼' : '▶' }}
              </button>
            </div>
            <pre v-show="expanded.routing" class="config-value">{{
              formatJson(snapshot.feature_routes)
            }}</pre>
          </div>
        </div>

        <!-- 知识配置 -->
        <div v-if="activeTab === 'knowledge'" class="config-section">
          <h3>知识配置</h3>
          <div class="config-item">
            <div class="config-header">
              <span class="config-name">知识库版本</span>
              <button class="btn-expand" @click="toggleExpand('knowledge')">
                {{ expanded.knowledge ? '▼' : '▶' }}
              </button>
            </div>
            <pre v-show="expanded.knowledge" class="config-value">{{
              formatJson(snapshot.kb_versions)
            }}</pre>
          </div>
        </div>

        <!-- 全部JSON -->
        <div v-if="activeTab === 'all'" class="config-section">
          <h3>完整配置快照 (JSON)</h3>
          <div class="config-item">
            <button class="btn-copy" @click="copyToClipboard">📋 复制</button>
          </div>
          <pre class="config-value full-json">{{ formatJson(snapshot) }}</pre>
        </div>
      </div>

      <!-- 操作按钮 -->
      <div class="actions">
        <button class="btn-export" @click="exportSnapshot">📥 导出为JSON</button>
        <button class="btn-refresh" @click="loadSnapshot">🔄 刷新</button>
      </div>
    </div>

    <!-- 未加载 -->
    <div v-else class="empty-state">
      <p>📭 请输入Run ID并加载快照</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'

interface Snapshot {
  id: string
  run_id: string
  created_at: string
  status: string
  model_profiles: Record<string, any>
  providers: Record<string, any>
  feature_routes: Record<string, any>
  kb_versions: Record<string, any>
  [key: string]: any
}

const router = useRouter()

const runId = ref<string>('')
const snapshot = ref<Snapshot | null>(null)
const isLoading = ref(false)
const activeTab = ref<string>('models')
const expanded = ref<Record<string, boolean>>({
  models: true,
  providers: true,
  routing: true,
  knowledge: true,
})

const tabs = ['models', 'providers', 'routing', 'knowledge', 'all']
const tabLabels: Record<string, string> = {
  models: '📊 模型配置',
  providers: '☁️ Provider',
  routing: '🔀 路由',
  knowledge: '📚 知识库',
  all: '📄 完整JSON',
}

const goBack = () => {
  router.back()
}

const loadSnapshot = async () => {
  if (!runId.value.trim()) {
    alert('请输入Run ID')
    return
  }

  isLoading.value = true
  try {
    const response = await fetch(`/api/v1/runs/${runId.value}/snapshot`)
    if (response.ok) {
      snapshot.value = await response.json()
    } else if (response.status === 404) {
      alert('未找到该Run的快照')
      snapshot.value = null
    } else {
      alert('加载快照失败')
    }
  } catch (error) {
    console.error('加载快照失败:', error)
    alert('加载快照失败')
  } finally {
    isLoading.value = false
  }
}

const formatTime = (dateStr: string): string => {
  if (!dateStr) return '—'
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN')
}

const formatJson = (obj: any): string => {
  try {
    return JSON.stringify(obj, null, 2)
  } catch {
    return String(obj)
  }
}

const toggleExpand = (key: string) => {
  expanded.value[key] = !expanded.value[key]
}

const copyToClipboard = () => {
  if (!snapshot.value) return
  const text = formatJson(snapshot.value)
  navigator.clipboard.writeText(text).then(() => {
    alert('已复制到剪贴板')
  }).catch(err => {
    console.error('复制失败:', err)
  })
}

const exportSnapshot = () => {
  if (!snapshot.value) return
  const data = JSON.stringify(snapshot.value, null, 2)
  const blob = new Blob([data], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `snapshot_${runId.value}_${Date.now()}.json`
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<style scoped>
.snapshot-container {
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

.run-selector {
  display: flex;
  gap: 10px;
  margin-bottom: 20px;
  background: white;
  padding: 15px;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.run-selector label {
  color: #555;
  font-size: 14px;
  min-width: 80px;
  display: flex;
  align-items: center;
}

.input-field {
  flex: 1;
  padding: 8px 12px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-size: 14px;
  font-family: monospace;
}

.input-field:focus {
  outline: none;
  border-color: #4CAF50;
  background-color: #f9fff9;
}

.btn-load {
  padding: 8px 16px;
  background: #4CAF50;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
  transition: background 0.2s;
}

.btn-load:hover {
  background: #45a049;
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

.snapshot-content {
  background: white;
  border-radius: 8px;
  padding: 20px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.snapshot-info {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 16px;
  margin-bottom: 20px;
  padding-bottom: 20px;
  border-bottom: 1px solid #eee;
}

.info-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.label {
  color: #666;
  font-size: 14px;
  font-weight: 500;
}

.value {
  color: #333;
  font-family: monospace;
  font-size: 12px;
  word-break: break-all;
}

.badge {
  display: inline-block;
  padding: 4px 8px;
  background: #d4edda;
  color: #155724;
  border-radius: 3px;
  font-size: 12px;
}

.tabs {
  display: flex;
  gap: 8px;
  margin-bottom: 20px;
  border-bottom: 1px solid #eee;
  overflow-x: auto;
}

.tab {
  padding: 10px 16px;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  color: #666;
  font-size: 14px;
  transition: all 0.2s;
  white-space: nowrap;
}

.tab:hover {
  color: #4CAF50;
}

.tab.active {
  color: #4CAF50;
  border-bottom-color: #4CAF50;
}

.tab-content {
  margin-bottom: 20px;
}

.config-section {
  margin-bottom: 16px;
}

.config-section h3 {
  margin: 0 0 12px 0;
  color: #333;
  font-size: 16px;
}

.config-item {
  background: #fafafa;
  border-radius: 4px;
  overflow: hidden;
}

.config-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: #f0f0f0;
  border-bottom: 1px solid #eee;
  cursor: pointer;
}

.config-name {
  font-weight: 500;
  color: #333;
  font-size: 14px;
}

.btn-expand,
.btn-copy {
  background: none;
  border: none;
  cursor: pointer;
  color: #4CAF50;
  font-size: 14px;
  padding: 4px 8px;
}

.btn-expand:hover,
.btn-copy:hover {
  color: #45a049;
}

.config-value {
  padding: 16px;
  background: white;
  border: 1px solid #eee;
  border-radius: 4px;
  font-size: 12px;
  line-height: 1.6;
  color: #666;
  overflow-x: auto;
  max-height: 400px;
  overflow-y: auto;
  margin: 0;
}

.config-value.full-json {
  max-height: 600px;
}

.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: #999;
}

.actions {
  display: flex;
  gap: 8px;
  justify-content: flex-start;
  padding-top: 20px;
  border-top: 1px solid #eee;
}

.btn-export,
.btn-refresh {
  padding: 8px 16px;
  background: white;
  border: 1px solid #ddd;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
  transition: all 0.2s;
}

.btn-export:hover,
.btn-refresh:hover {
  border-color: #4CAF50;
  color: #4CAF50;
}
</style>
