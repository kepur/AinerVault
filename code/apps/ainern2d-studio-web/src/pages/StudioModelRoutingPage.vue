<template>
  <div class="page-grid">
    <NTabs v-model:value="activeTab" type="card" animated size="large">
      
      <!-- TAB 1: AI 自动顾问 -->
      <NTabPane name="advisor" :tab="'✨ ' + t('routing.autoAdvisor')">
        <NCard :title="t('routing.title') + ' (Auto Router Advisor)'" :bordered="false" class="header-card">
          <template #header-extra>
            <NSpace>
              <NButton type="primary" size="large" @click="onAnalyze" :loading="isAnalyzing">
                <template #icon>✨</template>
                {{ t('routing.runAdvisor') }}
              </NButton>
            </NSpace>
          </template>
          <p style="color: var(--n-text-color-3)">
            {{ t('routing.advisorDesc') }}
          </p>
          <NFormItem :label="t('routing.selectProvider')" style="max-width: 400px; margin-top: 16px;">
            <NSelect 
              v-model:value="selectedAnalyzerId" 
              :options="analyzerOptions" 
              clearable 
              :placeholder="t('routing.autoSelect')" 
            />
          </NFormItem>
        </NCard>

        <div v-if="reportData" class="analysis-result-layout">
          <NCard :title="t('models.diagReport')" :bordered="false" class="report-card">
            <div class="markdown-body">
              <pre style="white-space: pre-wrap; font-family: inherit">{{ reportData.markdown_report }}</pre>
            </div>
          </NCard>

          <NCard :title="t('models.suggestedConfig')" :bordered="false" class="preview-card">
            <template #header-extra>
              <NButton type="warning" size="small" @click="onApply" :loading="isApplying">🚀 一键应用生效</NButton>
            </template>
            <NTabs type="segment" animated>
              <NTabPane name="profiles" :tab="t('models.profiles')">
                <NDataTable :columns="profileColumns" :data="reportData.suggested_profiles" :pagination="false" size="small" />
              </NTabPane>
              <NTabPane name="routes" :tab="t('models.routingRules')">
                <NDataTable :columns="routeColumns" :data="reportData.suggested_routes" :pagination="false" size="small" />
              </NTabPane>
            </NTabs>
          </NCard>
        </div>

        <div v-else-if="isAnalyzing" class="empty-state">
          <NSpin size="large" />
          <span style="margin-top: 16px; color: var(--n-text-color-3)">🧠 AI 正在分析模型生态布局，请稍候...</span>
        </div>
        
        <div v-else class="empty-state">
          <NEmpty :description="t('routing.startHint')" />
        </div>
      </NTabPane>

      <!-- TAB 2: 手动路由映射 -->
      <NTabPane name="manual" :tab="t('routing.manualRouting')">
        <NCard :title="t('models.coreRouting')" :bordered="false">
          <template #header-extra>
            <NButton type="primary" @click="onSaveManualRoute" :loading="isSavingManual">
              💾 保存当前路由
            </NButton>
          </template>

          <p style="color: var(--n-text-color-3); margin-bottom: 24px;">
            当系统在运行时请求对应场景的大模型能力时，将使用此处指定的模型 Profile。如果在"自动路由顾问"中一键配置过，这里会立刻显示同步的绑定状态。
          </p>

          <NForm label-placement="top">
            <NGrid :cols="2" :x-gap="24" :y-gap="20" responsive="screen" item-responsive>
              <NGridItem span="0:2 900:1" v-for="routeDef in manualRouteDefinitions" :key="routeDef.key">
                <NFormItem :label="routeDef.label">
                  <NSelect
                    v-model:value="workingRoutes[routeDef.key]"
                    :options="profileOptions"
                    clearable
                    placeholder="选择一个现有的 Model Profile"
                  />
                </NFormItem>
              </NGridItem>
            </NGrid>
          </NForm>
        </NCard>
      </NTabPane>

      <!-- TAB 3: MVP 系统必备清单 -->
      <NTabPane name="runtime" tab="⚡ 运行时路由">
        <NCard title="协商结果 → 运行时路由" :bordered="false">
          <template #header-extra>
            <NSpace>
              <NButton @click="loadRuntimeRouting" :loading="isLoadingRuntime">刷新运行时路由</NButton>
            </NSpace>
          </template>

          <p style="color: var(--n-text-color-3); margin-bottom: 18px;">
            这里展示来自 Ops Bridge 协商后的集成版本、当前写入到运行时路由的 Profile，以及最近一次快速试调用记录。
          </p>

          <div v-if="capabilityStats.length" class="capability-stats-grid">
            <div v-for="item in capabilityStats" :key="item.capability_type" class="capability-stat-card">
              <div class="capability-stat-card__header">
                <div class="capability-stat-card__title">{{ item.capability_type }}</div>
                <NTag :type="item.latest_status === 'success' ? 'success' : item.latest_status === 'failed' ? 'error' : 'default'" size="small" :bordered="false">
                  {{ item.latest_status === 'success' ? '最近成功' : item.latest_status === 'failed' ? '最近失败' : '暂无记录' }}
                </NTag>
              </div>
              <div class="capability-stat-card__metrics">
                <div>
                  <div class="capability-stat-card__label">成功率</div>
                  <div class="capability-stat-card__value">{{ formatSuccessRate(item.success_rate, item.total_runs) }}</div>
                </div>
                <div>
                  <div class="capability-stat-card__label">最近耗时</div>
                  <div class="capability-stat-card__value">{{ formatLatency(item.latest_latency_ms) }}</div>
                </div>
              </div>
              <div class="capability-stat-card__meta">
                <div>成功次数：{{ item.success_runs }} / {{ item.total_runs }}</div>
                <div>Provider：{{ item.latest_provider_name || '-' }}</div>
                <div>最近时间：{{ formatDateTime(item.latest_at) }}</div>
              </div>
            </div>
          </div>

          <NGrid :cols="2" :x-gap="16" :y-gap="16" responsive="screen" item-responsive>
            <NGridItem span="0:2 900:1">
              <NCard title="Stage Routes" size="small" embedded>
                <pre class="runtime-json">{{ JSON.stringify(runtimeRouting?.stage_routes || {}, null, 2) }}</pre>
              </NCard>
            </NGridItem>
            <NGridItem span="0:2 900:1">
              <NCard title="Feature Routes / Fallback" size="small" embedded>
                <pre class="runtime-json">{{ JSON.stringify({ feature_routes: runtimeRouting?.feature_routes || {}, fallback_chain: runtimeRouting?.fallback_chain || {} }, null, 2) }}</pre>
              </NCard>
            </NGridItem>
          </NGrid>

          <NDivider />

          <NDataTable
            :columns="runtimeColumns"
            :data="runtimeRouting?.items || []"
            :loading="isLoadingRuntime"
            :pagination="{ pageSize: 6 }"
            size="small"
            :bordered="false"
            :scroll-x="1400"
          />

          <NDivider />

          <NGrid :cols="2" :x-gap="16" :y-gap="16" responsive="screen" item-responsive>
            <NGridItem span="0:2 900:1">
              <NCard title="快速试调用" size="small" embedded>
                <NForm label-placement="top">
                  <NFormItem label="目标集成版本">
                    <NSelect
                      :value="quickRunIntegrationId"
                      :options="runtimeIntegrationOptions"
                      clearable
                      placeholder="选择一个集成版本"
                      @update:value="onSelectQuickRunIntegration"
                    />
                  </NFormItem>

                  <NFormItem label="当前能力">
                    <div class="runtime-kv">{{ selectedQuickRunCapability || '请先选择集成版本' }}</div>
                  </NFormItem>

                  <template v-if="selectedQuickRunCapability === 'llm_structured'">
                    <NFormItem label="Prompt">
                      <NInput :value="quickRunForm.prompt" type="textarea" :rows="4" @update:value="(value) => quickRunForm.prompt = value" />
                    </NFormItem>
                    <NFormItem label="System Prompt">
                      <NInput :value="quickRunForm.systemPrompt" type="textarea" :rows="2" @update:value="(value) => quickRunForm.systemPrompt = value" />
                    </NFormItem>
                    <NFormItem label="Max Tokens">
                      <NInput :value="quickRunForm.maxTokens" @update:value="(value) => quickRunForm.maxTokens = value" />
                    </NFormItem>
                  </template>

                  <template v-else-if="selectedQuickRunCapability === 'storyboard_t2i'">
                    <NFormItem label="Image Prompt">
                      <NInput :value="quickRunForm.prompt" type="textarea" :rows="4" @update:value="(value) => quickRunForm.prompt = value" />
                    </NFormItem>
                    <NFormItem label="Size">
                      <NSelect :value="quickRunForm.size" :options="imageSizeOptions" @update:value="(value) => quickRunForm.size = String(value || '1024x1024')" />
                    </NFormItem>
                    <NFormItem label="Style / Scene">
                      <NInput :value="quickRunForm.scene" @update:value="(value) => quickRunForm.scene = value" />
                    </NFormItem>
                  </template>

                  <template v-else-if="videoCapabilities.includes(selectedQuickRunCapability)">
                    <NFormItem label="Video Prompt">
                      <NInput :value="quickRunForm.prompt" type="textarea" :rows="4" @update:value="(value) => quickRunForm.prompt = value" />
                    </NFormItem>
                    <NGrid :cols="3" :x-gap="12">
                      <NGridItem>
                        <NFormItem label="Duration(s)">
                          <NSelect :value="quickRunForm.duration" :options="durationOptions" @update:value="(value) => quickRunForm.duration = String(value || '4')" />
                        </NFormItem>
                      </NGridItem>
                      <NGridItem>
                        <NFormItem label="FPS">
                          <NSelect :value="quickRunForm.fps" :options="fpsOptions" @update:value="(value) => quickRunForm.fps = String(value || '12')" />
                        </NFormItem>
                      </NGridItem>
                      <NGridItem>
                        <NFormItem label="Resolution">
                          <NSelect :value="quickRunForm.resolution" :options="resolutionOptions" @update:value="(value) => quickRunForm.resolution = String(value || '720p')" />
                        </NFormItem>
                      </NGridItem>
                    </NGrid>
                    <NFormItem v-if="selectedQuickRunCapability === 'video_i2v'" label="Image URL">
                      <NInput :value="quickRunForm.imageUrl" @update:value="(value) => quickRunForm.imageUrl = value" />
                    </NFormItem>
                  </template>

                  <template v-else-if="ttsCapabilities.includes(selectedQuickRunCapability)">
                    <NFormItem label="文本">
                      <NInput :value="quickRunForm.text" type="textarea" :rows="4" @update:value="(value) => quickRunForm.text = value" />
                    </NFormItem>
                    <NFormItem label="Voice">
                      <NSelect :value="quickRunForm.voice" :options="voiceOptions" @update:value="(value) => quickRunForm.voice = String(value || 'alloy')" />
                    </NFormItem>
                    <NFormItem label="Format">
                      <NSelect :value="quickRunForm.format" :options="formatOptions" @update:value="(value) => quickRunForm.format = String(value || 'mp3')" />
                    </NFormItem>
                  </template>

                  <template v-else-if="audioGenCapabilities.includes(selectedQuickRunCapability)">
                    <NFormItem label="Audio Prompt">
                      <NInput :value="quickRunForm.prompt" type="textarea" :rows="4" @update:value="(value) => quickRunForm.prompt = value" />
                    </NFormItem>
                    <NGrid :cols="2" :x-gap="12">
                      <NGridItem>
                        <NFormItem label="Duration(s)">
                          <NSelect :value="quickRunForm.duration" :options="audioDurationOptions" @update:value="(value) => quickRunForm.duration = String(value || '8')" />
                        </NFormItem>
                      </NGridItem>
                      <NGridItem>
                        <NFormItem label="Format">
                          <NSelect :value="quickRunForm.format" :options="formatOptions" @update:value="(value) => quickRunForm.format = String(value || 'mp3')" />
                        </NFormItem>
                      </NGridItem>
                    </NGrid>
                  </template>

                  <NFormItem label="补充参数(JSON)">
                    <NInput
                      :value="quickRunForm.extraJson"
                      type="textarea"
                      :rows="6"
                      @update:value="(value) => quickRunForm.extraJson = value"
                    />
                  </NFormItem>
                </NForm>
                <NSpace>
                  <NButton @click="resetQuickRunForm">载入能力示例</NButton>
                  <NButton type="primary" :loading="isQuickRunning" @click="onQuickRun">快速运行 / 试调用</NButton>
                </NSpace>
              </NCard>
            </NGridItem>

            <NGridItem span="0:2 900:1">
              <NCard title="最近试调用结果" size="small" embedded>
                <div v-if="quickRunResult" class="result-stack">
                  <div class="result-summary-grid">
                    <div class="result-tile">
                      <div class="result-tile__label">模式</div>
                      <div class="result-tile__value">{{ quickRunResult.mode }}</div>
                    </div>
                    <div class="result-tile">
                      <div class="result-tile__label">能力</div>
                      <div class="result-tile__value">{{ quickRunResult.integration.capability_type }}</div>
                    </div>
                    <div class="result-tile">
                      <div class="result-tile__label">Provider</div>
                      <div class="result-tile__value">{{ quickRunResult.integration.provider_name }}</div>
                    </div>
                    <div class="result-tile">
                      <div class="result-tile__label">Profile</div>
                      <div class="result-tile__value">{{ quickRunResult.profile_name || '-' }}</div>
                    </div>
                  </div>

                  <div class="result-panel">
                    <div class="result-panel__title">联通探测</div>
                    <div class="result-panel__line">status: {{ quickRunResult.probe?.status || '-' }}</div>
                    <div class="result-panel__line">detail: {{ quickRunResult.probe?.detail || '-' }}</div>
                    <div class="result-panel__line">latency_ms: {{ quickRunResult.probe?.latency_ms ?? '-' }}</div>
                  </div>

                  <div class="result-panel">
                    <div class="result-panel__title">真实调用摘要</div>
                    <div class="result-panel__line">ok: {{ quickRunResult.live_response?.ok ?? '-' }}</div>
                    <div class="result-panel__line">status_code: {{ quickRunResult.live_response?.status_code ?? '-' }}</div>
                    <div class="result-panel__line">detail: {{ quickRunResult.live_response?.detail || '-' }}</div>
                  </div>

                  <div class="result-panel">
                    <div class="result-panel__title">请求预览</div>
                    <pre class="runtime-json">{{ JSON.stringify(quickRunResult.request_preview || {}, null, 2) }}</pre>
                  </div>

                  <div class="result-panel">
                    <div class="result-panel__title">真实响应体</div>
                    <pre class="runtime-json">{{ JSON.stringify(quickRunResult.live_response?.body || quickRunResult.live_response || {}, null, 2) }}</pre>
                  </div>
                </div>
                <div v-else class="runtime-empty">尚未执行快速试调用</div>
              </NCard>
            </NGridItem>
          </NGrid>

          <NDivider />

          <NCard title="最近路由决策" size="small" embedded>
            <NDataTable
              :columns="decisionColumns"
              :data="runtimeRouting?.recent_decisions || []"
              :pagination="{ pageSize: 5 }"
              size="small"
              :bordered="false"
            />
          </NCard>
        </NCard>
      </NTabPane>

      <!-- TAB 4: MVP 系统必备清单 -->
      <NTabPane name="mvp" :tab="t('routing.mvpList')">
        <NCard title="系统最低可运行能力检测清单" :bordered="false" style="max-width: 800px; margin: 0 auto;">
          <NText depth="3" style="display:block;margin-bottom:16px;">
            检查当前接入的模型提供商（Provider）是否满足 Ainer Studio 的各核心功能基本需要。
          </NText>
          <NList bordered>
            <NListItem v-for="req in requirements" :key="req.key">
              <NSpace align="center" justify="space-between" style="width:100%">
                <NSpace align="center" :size="8">
                  <NTag :type="req.satisfied ? 'success' : 'error'" size="small" style="width: 28px; justify-content: center;">
                    {{ req.satisfied ? '✅' : '❌' }}
                  </NTag>
                  <span style="font-weight: 500;">{{ req.label }}</span>
                </NSpace>
                <NText v-if="req.satisfied" depth="3" style="font-size:12px">{{ req.satisfiedBy }}</NText>
                <NButton v-else size="tiny" type="primary" @click="activeTab='advisor'">尝试自动补齐缺口</NButton>
              </NSpace>
            </NListItem>
          </NList>

          <NDivider />
          <NStatistic label="MVP 能力点覆盖率">
            <template #default>
              {{ satisfiedCount }} / {{ requirements.length }}
            </template>
          </NStatistic>
        </NCard>
      </NTabPane>

    </NTabs>

    <!-- 消息提示区域 -->
    <div class="fixed-alerts">
      <NAlert v-if="message" type="success" :show-icon="true" closable @close="message=''">{{ message }}</NAlert>
      <NAlert v-if="errorMessage" type="error" :show-icon="true" closable @close="errorMessage=''">{{ errorMessage }}</NAlert>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref } from "vue";
import {
  NAlert,
  NButton,
  NCard,
  NDataTable,
  NDivider,
  NEmpty,
  NForm,
  NFormItem,
  NGrid,
  NGridItem,
  NInput,
  NList,
  NListItem,
  NSelect,
  NSpace,
  NSpin,
  NStatistic,
  NTabPane,
  NTabs,
  NTag,
  NText,
  type DataTableColumns
} from "naive-ui";
import {
  applyOpsRuntimeRouting,
  analyzeAutoRoutes,
  applyAutoRoutes,
  getOpsRuntimeRouting,
  getStageRouting,
  listModelProfiles,
  listProviders,
  quickRunOpsIntegration,
  rollbackOpsIntegration,
  upsertStageRouting
} from "@/api/product";
import { useI18n } from "@/composables/useI18n";

const { t } = useI18n();

const tenantId = ref("default");
const projectId = ref("default");

const activeTab = ref("advisor");

// MVP Requirements definition
const MVP_REQUIREMENTS = [
  { key: "text_generation", label: "LLM（文本生成）", capField: "supports_text_generation" },
  { key: "embedding", label: "Embedding（知识向量化）", capField: "supports_embedding" },
  { key: "image_generation", label: "Image Gen（文生图/图生图）", capField: "supports_image_generation" },
  { key: "video_generation", label: "Video Gen（视频生成）", capField: "supports_video_generation" },
  { key: "tts", label: "TTS（角色语音合成）", capField: "supports_tts" },
];

const manualRouteDefinitions = [
  { key: "route_novel_chapter_workspace", label: "小说章节核心创作 (route_novel_chapter_workspace)" },
  { key: "route_rag_query", label: "RAG 增强层知识检索 (route_rag_query)" },
  { key: "route_general_chat", label: "系统辅助与常规对话 (route_general_chat)" },
  { key: "route_image_gen", label: "小说实体概念/场景图像渲染 (route_image_gen)" },
  { key: "route_video_gen", label: "关键剧情视听转化 (route_video_gen)" },
  { key: "route_tts", label: "角色多语种有声合成 (route_tts)" },
];

// AI Advisor state
const isAnalyzing = ref(false);
const isApplying = ref(false);
const reportData = ref<any>(null);
const selectedAnalyzerId = ref<string | null>(null);

// Manual state
const workingRoutes = ref<Record<string, string>>({});
const isSavingManual = ref(false);
const isLoadingRuntime = ref(false);
const isApplyingRuntime = ref<string | null>(null);
const isPromotingRuntime = ref<string | null>(null);
const isQuickRunning = ref(false);
const runtimeRouting = ref<any>(null);
const quickRunResult = ref<any>(null);
const quickRunIntegrationId = ref<string | null>(null);
const ttsCapabilities = ["tts", "dialogue_tts", "narration_tts"];
const videoCapabilities = ["video_t2v", "video_i2v"];
const audioGenCapabilities = ["sfx", "bgm"];
const quickRunForm = ref({
  prompt: "生成一个简短连贯的测试样例",
  systemPrompt: "你是一个用于联调验证的轻量助手。",
  maxTokens: "64",
  size: "1024x1024",
  scene: "rainy night alley",
  duration: "4",
  fps: "12",
  resolution: "720p",
  imageUrl: "",
  text: "这是一个用于语音合成快速联调的测试句子。",
  voice: "alloy",
  format: "mp3",
  extraJson: '{\n  "scene": "rainy night alley"\n}',
});

const providers = ref<any[]>([]);
const profiles = ref<any[]>([]);

const message = ref("");
const errorMessage = ref("");

function stringifyError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function applyQuickRunPreset(capabilityType: string): void {
  if (capabilityType === "llm_structured") {
    quickRunForm.value = {
      prompt: "请生成一个简短、结构清晰的测试回复。",
      systemPrompt: "你是一个用于统一网关联调的测试助手。",
      maxTokens: "64",
      size: "1024x1024",
      scene: "rainy night alley",
      duration: "4",
      fps: "12",
      resolution: "720p",
      imageUrl: "",
      text: "这是一个用于语音合成快速联调的测试句子。",
      voice: "alloy",
      format: "mp3",
      extraJson: '{\n  "scene": "rainy night alley"\n}',
    };
    return;
  }
  if (capabilityType === "storyboard_t2i") {
    quickRunForm.value = {
      prompt: "电影感雨夜小巷，霓虹灯反射在湿润地面，构图稳定，角色背影。",
      systemPrompt: "",
      maxTokens: "64",
      size: "1024x1024",
      scene: "cinematic noir",
      duration: "4",
      fps: "12",
      resolution: "720p",
      imageUrl: "",
      text: "这是一个用于语音合成快速联调的测试句子。",
      voice: "alloy",
      format: "mp3",
      extraJson: '{\n  "style": "cinematic"\n}',
    };
    return;
  }
  if (capabilityType === "video_t2v") {
    quickRunForm.value = {
      prompt: "镜头缓慢推进到雨夜街道，霓虹光影反射在路面上。",
      systemPrompt: "",
      maxTokens: "64",
      size: "1024x1024",
      scene: "rainy night alley",
      duration: "4",
      fps: "12",
      resolution: "720p",
      imageUrl: "",
      text: "这是一个用于语音合成快速联调的测试句子。",
      voice: "alloy",
      format: "mp3",
      extraJson: '{\n  "camera_motion": "slow_push"\n}',
    };
    return;
  }
  if (capabilityType === "video_i2v") {
    quickRunForm.value = {
      prompt: "让角色衣摆和雨滴产生轻微动态。",
      systemPrompt: "",
      maxTokens: "64",
      size: "1024x1024",
      scene: "rainy night alley",
      duration: "4",
      fps: "12",
      resolution: "720p",
      imageUrl: "https://example.com/reference-frame.png",
      text: "这是一个用于语音合成快速联调的测试句子。",
      voice: "alloy",
      format: "mp3",
      extraJson: '{\n  "motion_strength": 0.35\n}',
    };
    return;
  }
  if (ttsCapabilities.includes(capabilityType)) {
    quickRunForm.value = {
      prompt: "生成一个简短连贯的测试样例",
      systemPrompt: "",
      maxTokens: "64",
      size: "1024x1024",
      scene: "rainy night alley",
      duration: "4",
      fps: "12",
      resolution: "720p",
      imageUrl: "",
      text: "这是一个用于语音合成快速联调的测试句子。",
      voice: "alloy",
      format: "mp3",
      extraJson: "{}",
    };
    return;
  }
  if (audioGenCapabilities.includes(capabilityType)) {
    quickRunForm.value = {
      prompt: capabilityType === "sfx" ? "生成一段短促的木门开启音效。" : "生成一段神秘氛围的短背景音乐。",
      systemPrompt: "",
      maxTokens: "64",
      size: "1024x1024",
      scene: "rainy night alley",
      duration: capabilityType === "sfx" ? "6" : "15",
      fps: "12",
      resolution: "720p",
      imageUrl: "",
      text: "这是一个用于语音合成快速联调的测试句子。",
      voice: "alloy",
      format: "mp3",
      extraJson: capabilityType === "sfx" ? '{\n  "category": "door_open"\n}' : '{\n  "mood": "mysterious"\n}',
    };
    return;
  }
  quickRunForm.value = {
    prompt: "生成一个简短连贯的测试样例",
    systemPrompt: "",
    maxTokens: "64",
    size: "1024x1024",
    scene: "rainy night alley",
    duration: "4",
    fps: "12",
    resolution: "720p",
    imageUrl: "",
    text: "这是一个用于语音合成快速联调的测试句子。",
    voice: "alloy",
    format: "mp3",
    extraJson: '{\n  "prompt": "生成一个简短连贯的测试样例",\n  "scene": "rainy night alley"\n}',
  };
}

function clearNotice(): void {
  message.value = "";
  errorMessage.value = "";
}

function onSelectQuickRunIntegration(value: string | number | null): void {
  quickRunIntegrationId.value = value ? String(value) : null;
  applyQuickRunPreset(selectedQuickRunItem.value?.capability_type || "");
}

function resetQuickRunForm(): void {
  applyQuickRunPreset(selectedQuickRunCapability.value || "");
}

// Computeds
const requirements = computed(() => {
  return MVP_REQUIREMENTS.map(req => {
    const hasCap = providers.value.some((prov: any) => {
      const flags = prov.capability_flags || {};
      return flags[req.capField];
    });
    const matchingProfile = profiles.value.find(p =>
      p.purpose === req.key || (p.capability_tags && p.capability_tags.includes(req.key))
    );
    return {
      key: req.key,
      label: req.label,
      satisfied: hasCap || !!matchingProfile,
      satisfiedBy: matchingProfile?.name || (hasCap ? "(检测到 Provider 支持)" : ""),
    };
  });
});

const satisfiedCount = computed(() => requirements.value.filter(r => r.satisfied).length);

const analyzerOptions = computed(() => {
  return providers.value
    .filter(p => p.capability_flags?.supports_text_generation)
    .map(p => ({
      label: p.name,
      value: p.id
    }));
});

const profileOptions = computed(() => {
  return profiles.value.map(p => ({
    label: `[${p.purpose}] ${p.name} (${p.provider_model_name})`,
    value: p.name
  }));
});

const profileColumns: DataTableColumns<any> = [
  { title: "Profile 名称", key: "name" },
  { title: "请求引擎", key: "provider_model_name" },
  { title: "能力偏向", key: "purpose", render: (row: any) => h(NTag, { type: 'info', size: 'small' }, { default: () => row.purpose }) },
];

const routeColumns: DataTableColumns<any> = [
  { title: "系统调用路由键", key: "route_key" },
  { title: "指向的内部 Profile", key: "profile_name", render: (row: any) => h(NTag, { type: 'warning', size: 'small', bordered: false }, { default: () => row.profile_name }) },
];

const runtimeIntegrationOptions = computed(() => {
  return (runtimeRouting.value?.items || []).map((item: any) => ({
    label: `[${item.capability_type}] ${item.provider_name} / v${item.version}`,
    value: item.integration_id,
  }));
});

const selectedQuickRunItem = computed(() => {
  return (runtimeRouting.value?.items || []).find((item: any) => item.integration_id === quickRunIntegrationId.value) || null;
});

const selectedQuickRunCapability = computed(() => selectedQuickRunItem.value?.capability_type || "");

const capabilityStats = computed(() => runtimeRouting.value?.capability_stats || []);

const imageSizeOptions = [
  { label: "1024x1024", value: "1024x1024" },
  { label: "1536x1024", value: "1536x1024" },
  { label: "1024x1536", value: "1024x1536" },
];

const durationOptions = [
  { label: "4s", value: "4" },
  { label: "6s", value: "6" },
  { label: "8s", value: "8" },
];

const audioDurationOptions = [
  { label: "6s", value: "6" },
  { label: "8s", value: "8" },
  { label: "15s", value: "15" },
  { label: "30s", value: "30" },
];

const fpsOptions = [
  { label: "12", value: "12" },
  { label: "18", value: "18" },
  { label: "24", value: "24" },
];

const resolutionOptions = [
  { label: "720p", value: "720p" },
  { label: "1080p", value: "1080p" },
  { label: "1440p", value: "1440p" },
];

const voiceOptions = [
  { label: "alloy", value: "alloy" },
  { label: "nova", value: "nova" },
  { label: "echo", value: "echo" },
  { label: "fable", value: "fable" },
];

const formatOptions = [
  { label: "mp3", value: "mp3" },
  { label: "wav", value: "wav" },
  { label: "aac", value: "aac" },
];

const runtimeColumns: DataTableColumns<any> = [
  {
    title: "Capability",
    key: "capability_type",
    width: 180,
    render: (row: any) => h("div", [
      h("div", { style: "font-weight: 600;" }, row.capability_type),
      h("div", { style: "font-size: 12px; color: var(--n-text-color-3);" }, `tier=${row.tier} / v${row.version}`),
    ]),
  },
  {
    title: "Provider/Profile",
    key: "provider_name",
    width: 230,
    render: (row: any) => h("div", [
      h("div", { style: "font-weight: 600;" }, row.provider_name),
      h("div", { style: "font-size: 12px; color: var(--n-text-color-3);" }, row.profile_name || "-"),
    ]),
  },
  {
    title: "运行时路由",
    key: "runtime_route_key",
    width: 260,
    render: (row: any) => h("div", [
      h("div", row.runtime_route_key),
      h("div", { style: "font-size: 12px; color: var(--n-text-color-3);" }, `${row.feature_route_key} → ${row.applied_profile_name || '-'}`),
    ]),
  },
  {
    title: "Mapping",
    key: "mapping_status",
    width: 120,
    render: (row: any) => h(NTag, { size: "small", bordered: false, type: row.mapping_status === "mapped" ? "success" : row.mapping_status === "partial" ? "warning" : "default" }, { default: () => row.mapping_status }),
  },
  {
    title: "写入状态",
    key: "applied_route_profile_name",
    width: 180,
    render: (row: any) => row.applied_route_profile_name || "未写入",
  },
  {
    title: "Actions",
    key: "actions",
    width: 260,
    render: (row: any) => h(NSpace, { size: 6 }, () => [
      h(NButton, {
        size: "small",
        type: "primary",
        loading: isApplyingRuntime.value === row.integration_id,
        onClick: () => onApplyRuntimeRoute(row),
      }, { default: () => "写入运行时路由" }),
      h(NButton, {
        size: "small",
        type: "warning",
        loading: isPromotingRuntime.value === row.integration_id,
        onClick: () => onPromoteAndApplyRuntimeRoute(row),
      }, { default: () => "设主并写路由" }),
      h(NButton, {
        size: "small",
        loading: isQuickRunning.value && quickRunIntegrationId.value === row.integration_id,
        onClick: () => onQuickRun(row.integration_id),
      }, { default: () => "快速试调用" }),
    ]),
  },
];

const decisionColumns: DataTableColumns<any> = [
  { title: "时间", key: "created_at", width: 180, render: (row: any) => row.created_at ? new Date(row.created_at).toLocaleString() : "-" },
  { title: "Capability", key: "capability_type", width: 160 },
  { title: "Provider", key: "provider_name", width: 180, render: (row: any) => row.provider_name || row.provider_key || "-" },
  { title: "Profile", key: "profile_name", width: 180, render: (row: any) => row.profile_name || "-" },
  { title: "模式", key: "mode", width: 120, render: (row: any) => row.mode || "-" },
  {
    title: "结果",
    key: "live_ok",
    width: 180,
    render: (row: any) => {
      if (row.live_ok == null && row.probe_ok == null) {
        return "-";
      }
      if (row.live_ok != null) {
        return row.live_ok ? `真实调用成功 / ${row.live_status_code || '-'}` : `真实调用失败 / ${row.live_status_code || row.probe_detail || '-'}`;
      }
      return row.probe_ok ? `探测成功 / ${row.probe_detail || ''}` : `探测失败 / ${row.probe_detail || ''}`;
    },
  },
  {
    title: "耗时",
    key: "live_latency_ms",
    width: 120,
    render: (row: any) => formatLatency(row.live_latency_ms ?? row.probe_latency_ms),
  },
];

function formatLatency(value?: number | null): string {
  return typeof value === "number" && Number.isFinite(value) ? `${value} ms` : "-";
}

function formatDateTime(value?: string | null): string {
  return value ? new Date(value).toLocaleString() : "-";
}

function formatSuccessRate(rate?: number | null, totalRuns?: number | null): string {
  if (!totalRuns) {
    return "-";
  }
  const normalized = typeof rate === "number" && Number.isFinite(rate) ? rate : 0;
  return `${normalized.toFixed(1)}%`;
}

// API triggers
async function loadBaseData() {
  try {
    const [provRes, profRes, routerRes] = await Promise.all([
      listProviders(tenantId.value, projectId.value),
      listModelProfiles({ tenant_id: tenantId.value, project_id: projectId.value }),
      getStageRouting(tenantId.value, projectId.value)
    ]);
    providers.value = provRes;
    profiles.value = profRes;
    const routes: Record<string, string> = {};
    for (const [key, value] of Object.entries(routerRes.routes || {})) {
      if (typeof value === "string" && value.trim()) {
        routes[key] = value;
      }
    }
    workingRoutes.value = routes;
    await loadRuntimeRouting();
  } catch (error) {
    console.error("Failed to load initial data", error);
  }
}

function parseQuickRunPayload(): Record<string, unknown> {
  const trimmed = quickRunForm.value.extraJson.trim();
  const extra = trimmed
    ? (() => {
        const parsed = JSON.parse(trimmed);
        if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
          throw new Error("补充参数必须是 JSON 对象");
        }
        return parsed as Record<string, unknown>;
      })()
    : {};

  if (selectedQuickRunCapability.value === "llm_structured") {
    return {
      prompt: quickRunForm.value.prompt,
      system_prompt: quickRunForm.value.systemPrompt,
      max_tokens: Number(quickRunForm.value.maxTokens || "64"),
      ...extra,
    };
  }
  if (selectedQuickRunCapability.value === "storyboard_t2i") {
    return {
      prompt: quickRunForm.value.prompt,
      size: quickRunForm.value.size,
      scene: quickRunForm.value.scene,
      ...extra,
    };
  }
  if (selectedQuickRunCapability.value === "video_t2v") {
    return {
      prompt: quickRunForm.value.prompt,
      duration: Number(quickRunForm.value.duration || "4"),
      fps: Number(quickRunForm.value.fps || "12"),
      resolution: quickRunForm.value.resolution,
      scene: quickRunForm.value.scene,
      ...extra,
    };
  }
  if (selectedQuickRunCapability.value === "video_i2v") {
    return {
      prompt: quickRunForm.value.prompt,
      image_url: quickRunForm.value.imageUrl,
      duration: Number(quickRunForm.value.duration || "4"),
      fps: Number(quickRunForm.value.fps || "12"),
      resolution: quickRunForm.value.resolution,
      ...extra,
    };
  }
  if (ttsCapabilities.includes(selectedQuickRunCapability.value)) {
    return {
      text: quickRunForm.value.text,
      prompt: quickRunForm.value.text,
      voice: quickRunForm.value.voice,
      format: quickRunForm.value.format,
      ...extra,
    };
  }
  if (audioGenCapabilities.includes(selectedQuickRunCapability.value)) {
    return {
      prompt: quickRunForm.value.prompt,
      duration: Number(quickRunForm.value.duration || "8"),
      format: quickRunForm.value.format,
      ...extra,
    };
  }
  return extra;
}

async function loadRuntimeRouting(): Promise<void> {
  isLoadingRuntime.value = true;
  try {
    runtimeRouting.value = await getOpsRuntimeRouting({
      tenant_id: tenantId.value,
      project_id: projectId.value,
    });
    if (!quickRunIntegrationId.value && runtimeRouting.value?.items?.length) {
      quickRunIntegrationId.value = runtimeRouting.value.items[0].integration_id;
      applyQuickRunPreset(runtimeRouting.value.items[0].capability_type || "");
    }
  } catch (error) {
    errorMessage.value = `加载运行时路由失败: ${stringifyError(error)}`;
  } finally {
    isLoadingRuntime.value = false;
  }
}

async function onApplyRuntimeRoute(row: any): Promise<void> {
  clearNotice();
  isApplyingRuntime.value = row.integration_id;
  try {
    runtimeRouting.value = await applyOpsRuntimeRouting({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      integration_id: row.integration_id,
    });
    message.value = `已将 ${row.capability_type} 写入运行时路由`; 
  } catch (error) {
    errorMessage.value = `写入运行时路由失败: ${stringifyError(error)}`;
  } finally {
    isApplyingRuntime.value = null;
  }
}

async function onPromoteAndApplyRuntimeRoute(row: any): Promise<void> {
  clearNotice();
  isPromotingRuntime.value = row.integration_id;
  try {
    if (row.status !== "active") {
      await rollbackOpsIntegration(row.integration_id, {
        tenant_id: tenantId.value,
        project_id: projectId.value,
      });
    }
    runtimeRouting.value = await applyOpsRuntimeRouting({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      integration_id: row.integration_id,
    });
    message.value = `已将 ${row.capability_type} 设为主版本并写入运行时路由`;
  } catch (error) {
    errorMessage.value = `设主并写路由失败: ${stringifyError(error)}`;
  } finally {
    isPromotingRuntime.value = null;
  }
}

async function onQuickRun(integrationId?: string): Promise<void> {
  clearNotice();
  isQuickRunning.value = true;
  try {
    const targetIntegrationId = integrationId || quickRunIntegrationId.value || undefined;
    quickRunResult.value = await quickRunOpsIntegration({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      integration_id: targetIntegrationId,
      sample_input: parseQuickRunPayload(),
      probe_connectivity: true,
    });
    quickRunIntegrationId.value = quickRunResult.value?.integration?.integration_id || quickRunIntegrationId.value;
    await loadRuntimeRouting();
    message.value = "快速试调用完成";
  } catch (error) {
    errorMessage.value = `快速试调用失败: ${stringifyError(error)}`;
  } finally {
    isQuickRunning.value = false;
  }
}

async function onAnalyze(): Promise<void> {
  clearNotice();
  isAnalyzing.value = true;
  reportData.value = null;
  try {
    const res = await analyzeAutoRoutes({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      analyzer_provider_id: selectedAnalyzerId.value || undefined,
    });
    reportData.value = res;
    message.value = "诊断分析成功！请预览配置。";
  } catch (error) {
    errorMessage.value = `分析失败: ${stringifyError(error)}`;
  } finally {
    isAnalyzing.value = false;
  }
}

async function onApply(): Promise<void> {
  if (!reportData.value) return;
  clearNotice();
  isApplying.value = true;
  try {
    await applyAutoRoutes({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      profiles: reportData.value.suggested_profiles || [],
      routes: reportData.value.suggested_routes || [],
    });
    message.value = "自动配置生效成功！";
    await loadBaseData(); // Reload to reflect changes in manual tab and MVP
  } catch (error) {
    errorMessage.value = `应用失败: ${stringifyError(error)}`;
  } finally {
    isApplying.value = false;
  }
}

async function onSaveManualRoute(): Promise<void> {
  clearNotice();
  isSavingManual.value = true;
  try {
    const cleanRoutes = { ...workingRoutes.value };
    // Remove empty keys
    for (const k in cleanRoutes) {
      if (!cleanRoutes[k]) {
        delete cleanRoutes[k];
      }
    }
    await upsertStageRouting({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      routes: cleanRoutes,
      fallback_chain: {},
      feature_routes: {}
    });
    message.value = "手动路由映射保存成功！";
  } catch (error) {
    errorMessage.value = `保存失败: ${stringifyError(error)}`;
  } finally {
    isSavingManual.value = false;
  }
}

onMounted(() => {
  void loadBaseData();
});
</script>

<style scoped>
.page-grid {
  padding: 8px 16px;
  position: relative;
  min-height: calc(100vh - 120px);
}

.header-card {
  margin-bottom: 16px;
}

.analysis-result-layout {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
}

@media (max-width: 1200px) {
  .analysis-result-layout {
    grid-template-columns: 1fr;
  }
}

.report-card, .preview-card {
  height: 100%;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  margin-top: 80px;
}

.fixed-alerts {
  position: fixed;
  bottom: 24px;
  right: 24px;
  z-index: 2000;
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-width: 400px;
}

.runtime-json {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.55;
  font-size: 12px;
  color: var(--n-text-color-2);
}

.runtime-kv {
  padding: 8px 10px;
  border-radius: 8px;
  background: var(--n-color-embedded);
  font-size: 13px;
  color: var(--n-text-color-2);
}

.capability-stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
  margin-bottom: 16px;
}

.capability-stat-card {
  padding: 14px;
  border-radius: 12px;
  background: var(--n-color-embedded);
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.capability-stat-card__header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.capability-stat-card__title {
  font-weight: 600;
  color: var(--n-text-color-1);
}

.capability-stat-card__metrics {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.capability-stat-card__label {
  font-size: 12px;
  color: var(--n-text-color-3);
  margin-bottom: 4px;
}

.capability-stat-card__value {
  font-size: 18px;
  font-weight: 700;
  color: var(--n-text-color-1);
}

.capability-stat-card__meta {
  font-size: 12px;
  color: var(--n-text-color-2);
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.runtime-empty {
  color: var(--n-text-color-3);
  font-size: 13px;
}

.result-stack {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.result-summary-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.result-tile {
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--n-color-embedded);
}

.result-tile__label {
  font-size: 12px;
  color: var(--n-text-color-3);
  margin-bottom: 4px;
}

.result-tile__value {
  font-size: 13px;
  font-weight: 600;
  color: var(--n-text-color-1);
  word-break: break-word;
}

.result-panel {
  padding: 10px 12px;
  border-radius: 10px;
  background: var(--n-color-embedded);
}

.result-panel__title {
  font-size: 13px;
  font-weight: 600;
  margin-bottom: 6px;
}

.result-panel__line {
  font-size: 12px;
  line-height: 1.6;
  color: var(--n-text-color-2);
  word-break: break-word;
}
</style>
