<template>
  <div class="audit-logs-container">
    <!-- 顶部标题 -->
    <div class="page-header">
      <h1>📋 审计日志</h1>
      <p class="subtitle">查看所有系统操作记录</p>
    </div>

    <!-- 过滤区域 -->
    <div class="filters-section">
      <div class="filter-group">
        <label>项目ID (可选):</label>
        <input
          v-model="projectId"
          type="text"
          placeholder="留空显示全部项目"
          class="filter-input"
        />
      </div>
      <div class="filter-group">
        <label>事件类型过滤:</label>
        <input
          v-model="eventTypeFilter"
          type="text"
          placeholder="例: chapter.ai_expansion"
          class="filter-input"
        />
      </div>
      <div class="filter-group">
        <label>记录数:</label>
        <select v-model.number="limit" class="filter-select">
          <option value="20">20条</option>
          <option value="50">50条</option>
          <option value="100">100条</option>
          <option value="200">200条</option>
        </select>
      </div>
      <button class="btn-refresh" @click="loadLogs">🔄 刷新</button>
    </div>

    <!-- 加载状态 -->
    <div v-if="isLoading" class="loading">
      <div class="spinner"></div>
      <p>加载中...</p>
    </div>

    <!-- 日志表格 -->
    <div v-else-if="filteredLogs.length > 0" class="logs-table-container">
      <table class="logs-table">
        <thead>
          <tr>
            <th>时间</th>
            <th>事件类型</th>
            <th>生产者模块</th>
            <th>Run ID</th>
            <th>Job ID</th>
            <th>详情</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="log in filteredLogs" :key="log.event_id" class="log-row">
            <td class="time-col">
              {{ formatTime(log.occurred_at) }}
            </td>
            <td class="event-type-col">
              <span class="badge" :class="getEventBadgeClass(log.event_type)">
                {{ log.event_type }}
              </span>
            </td>
            <td class="producer-col">{{ log.producer }}</td>
            <td class="id-col">{{ log.run_id || '—' }}</td>
            <td class="id-col">{{ log.job_id || '—' }}</td>
            <td class="detail-col">
              <button
                class="btn-expand"
                @click="toggleDetail(log.event_id)"
              >
                {{ expandedLogs[log.event_id] ? '▼' : '▶' }}
              </button>
            </td>
          </tr>
          <!-- 展开详情行 -->
          <tr
            v-for="log in filteredLogs"
            v-show="expandedLogs[log.event_id]"
            :key="`${log.event_id}-detail`"
            class="detail-row"
          >
            <td colspan="6">
              <div class="detail-content">
                <h4>详细信息</h4>
                <pre>{{ JSON.stringify(log.payload, null, 2) }}</pre>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- 无数据 -->
    <div v-else class="empty-state">
      <p>📭 没有找到匹配的日志记录</p>
    </div>

    <!-- 统计信息 -->
    <div v-if="logs.length > 0" class="stats-section">
      <p>显示 {{ filteredLogs.length }} / {{ logs.length }} 条记录</p>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'

interface AuditLog {
  event_id: string
  event_type: string
  producer: string
  occurred_at: string
  run_id: string | null
  job_id: string | null
  payload: Record<string, any>
}

import { useI18n } from "@/composables/useI18n";

const logs = ref<AuditLog[]>([])
const { t } = useI18n();

const isLoading = ref(false)
const projectId = ref<string>('')
const eventTypeFilter = ref<string>('')
const limit = ref<number>(50)
const expandedLogs = ref<Record<string, boolean>>({})

const filteredLogs = computed(() => {
  return logs.value.filter(log => {
    if (eventTypeFilter.value && !log.event_type.includes(eventTypeFilter.value)) {
      return false
    }
    return true
  })
})

const loadLogs = async () => {
  isLoading.value = true
  try {
    const params = new URLSearchParams({
      tenant_id: 'default-tenant',
      limit: limit.value.toString(),
    })
    if (projectId.value) {
      params.append('project_id', projectId.value)
    }

    const response = await fetch(`/api/v1/auth/audit/logs?${params}`)
    if (response.ok) {
      logs.value = await response.json()
    }
  } catch (error) {
    console.error('加载审计日志失败:', error)
    alert('加载审计日志失败')
  } finally {
    isLoading.value = false
  }
}

const formatTime = (dateStr: string): string => {
  const date = new Date(dateStr)
  return date.toLocaleString('zh-CN')
}

const getEventBadgeClass = (eventType: string): string => {
  if (eventType.includes('ai_expansion')) return 'badge-success'
  if (eventType.includes('error') || eventType.includes('failed')) return 'badge-error'
  if (eventType.includes('task')) return 'badge-info'
  return 'badge-default'
}

const toggleDetail = (eventId: string) => {
  expandedLogs.value[eventId] = !expandedLogs.value[eventId]
}

onMounted(() => {
  loadLogs()
})
</script>

<style scoped>
.audit-logs-container {
  padding: 20px;
  background: #f5f5f5;
  min-height: 100vh;
}

.page-header {
  margin-bottom: 30px;
}

.page-header h1 {
  font-size: 28px;
  margin: 0;
  color: #333;
}

.subtitle {
  color: #666;
  margin-top: 5px;
  font-size: 14px;
}

.filters-section {
  display: flex;
  gap: 15px;
  margin-bottom: 20px;
  background: white;
  padding: 15px;
  border-radius: 8px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}

.filter-group {
  display: flex;
  align-items: center;
  gap: 8px;
}

.filter-group label {
  font-size: 14px;
  color: #555;
  min-width: 80px;
}

.filter-input,
.filter-select {
  padding: 8px 12px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-size: 14px;
}

.filter-input:focus,
.filter-select:focus {
  outline: none;
  border-color: #4CAF50;
  background-color: #f9fff9;
}

.btn-refresh {
  padding: 8px 16px;
  background: #4CAF50;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
  transition: background 0.2s;
}

.btn-refresh:hover {
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

.logs-table-container {
  background: white;
  border-radius: 8px;
  overflow: hidden;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.logs-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 14px;
}

.logs-table thead {
  background: #f5f5f5;
  border-bottom: 2px solid #ddd;
}

.logs-table thead th {
  padding: 12px 16px;
  text-align: left;
  font-weight: 600;
  color: #333;
}

.log-row {
  border-bottom: 1px solid #eee;
  transition: background 0.2s;
}

.log-row:hover {
  background: #f9f9f9;
}

.time-col {
  padding: 12px 16px;
  color: #666;
  font-family: monospace;
  font-size: 12px;
}

.event-type-col {
  padding: 12px 16px;
}

.badge {
  display: inline-block;
  padding: 4px 8px;
  border-radius: 3px;
  font-size: 12px;
  font-weight: 500;
}

.badge-success {
  background: #d4edda;
  color: #155724;
}

.badge-error {
  background: #f8d7da;
  color: #721c24;
}

.badge-info {
  background: #d1ecf1;
  color: #0c5460;
}

.badge-default {
  background: #e2e3e5;
  color: #383d41;
}

.producer-col,
.id-col {
  padding: 12px 16px;
  color: #666;
  font-family: monospace;
  font-size: 12px;
}

.detail-col {
  padding: 12px 16px;
  text-align: center;
}

.btn-expand {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 14px;
  padding: 4px 8px;
  color: #4CAF50;
  transition: color 0.2s;
}

.btn-expand:hover {
  color: #45a049;
}

.detail-row {
  background: #fafafa;
}

.detail-content {
  padding: 16px;
}

.detail-content h4 {
  margin: 0 0 10px 0;
  color: #333;
}

.detail-content pre {
  background: #f5f5f5;
  padding: 12px;
  border-radius: 4px;
  overflow-x: auto;
  font-size: 12px;
  color: #666;
  margin: 0;
  max-height: 300px;
}

.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: #999;
}

.stats-section {
  margin-top: 20px;
  padding: 15px;
  background: white;
  border-radius: 8px;
  text-align: right;
  color: #666;
  font-size: 14px;
}
</style>
