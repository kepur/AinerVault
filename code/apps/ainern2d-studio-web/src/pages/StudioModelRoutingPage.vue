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
  analyzeAutoRoutes,
  applyAutoRoutes,
  getStageRouting,
  listModelProfiles,
  listProviders,
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

const providers = ref<any[]>([]);
const profiles = ref<any[]>([]);

const message = ref("");
const errorMessage = ref("");

function stringifyError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function clearNotice(): void {
  message.value = "";
  errorMessage.value = "";
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
    workingRoutes.value = routerRes.routes || {};
  } catch (error) {
    console.error("Failed to load initial data", error);
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
</style>
