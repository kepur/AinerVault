<template>
  <div class="page-grid">
    <div class="provider-layout">
      <!-- 左栏：Provider 列表 -->
      <div class="left-panel">
        <NCard size="small" :bordered="false" class="provider-list-card">
          <template #header>已接入厂商 (Providers)</template>
          <template #header-extra>
            <NButton size="small" type="primary" secondary @click="onAddNewProvider">{{ t('common.create') }}</NButton>
          </template>
          <NInput v-model:value="providerKeyword" placeholder="过滤厂商..." clearable style="margin-bottom: 12px" />
          <NList hoverable clickable>
            <NListItem
              v-for="prov in filteredProviders"
              :key="prov.id"
              class="provider-item"
              :class="{ 'active-item': selectedProviderId === prov.id }"
              @click="onSelectProvider(prov)"
            >
              <NThing :title="prov.name" :description="prov.endpoint" />
            </NListItem>
            <NEmpty v-if="filteredProviders.length === 0" :description="t('common.noData')" style="margin-top: 24px" />
          </NList>
        </NCard>
      </div>

      <!-- 右栏：Provider 详情编辑 -->
      <div class="right-panel">
        <NCard v-if="selectedProviderId || isAddingNew" :title="isAddingNew ? '接入新 Provider' : `配置: ${providerName}`" :bordered="false" class="provider-detail-card">
          <template #header-extra>
            <NSpace>
              <NPopconfirm v-if="!isAddingNew" @positive-click="onDeleteProvider(selectedProviderId)">
                <template #trigger>
                  <NButton type="error" size="small" tertiary>{{ t('common.delete') }}</NButton>
                </template>
                确认删除此 Provider？
              </NPopconfirm>
              <NButton type="primary" size="small" @click="onUpsertProvider" :loading="isSaving">{{ t('common.save') }}</NButton>
            </NSpace>
          </template>

          <NTabs type="line" animated>
            <NTabPane name="config" :tab="t('models.endpoint')">
              <NForm label-placement="top" class="detail-form">
                <NGrid :cols="2" :x-gap="24" :y-gap="8" responsive="screen" item-responsive>
                  <NGridItem span="0:2 640:1">
                    <NFormItem label="Provider Name / 标识">
                      <NInput v-model:value="providerName" placeholder="如: openai, anthropic" />
                    </NFormItem>
                  </NGridItem>
                  <NGridItem span="0:2 640:1">
                    <NFormItem label="Endpoint (API Base URL)">
                      <NInput v-model:value="providerEndpoint" placeholder="https://api.openai.com/v1" />
                    </NFormItem>
                  </NGridItem>
                  <NGridItem span="0:2 640:1">
                    <NFormItem label="Auth Mode">
                      <NSelect v-model:value="providerAuthMode" :options="authModeOptions" />
                    </NFormItem>
                  </NGridItem>
                  <NGridItem span="0:2 640:1">
                    <NFormItem label="Access Token / API Key">
                      <NInput v-model:value="providerToken" type="password" show-password-on="click" />
                    </NFormItem>
                  </NGridItem>
                  <NGridItem span="2">
                    <NFormItem label="支持的模型清单 (Model Catalog, 逗号分隔, AI自动路由会使用此列表)">
                      <NInput v-model:value="providerModelCatalogCsv" placeholder="gpt-4o, gpt-4o-mini, text-embedding-3-large" type="textarea" :autosize="{ minRows: 3 }" />
                    </NFormItem>
                  </NGridItem>
                </NGrid>
              </NForm>
            </NTabPane>

            <NTabPane name="caps" :tab="t('models.capabilityList')">
              <div class="caps-panel">
                <NAlert type="info" :show-icon="true" style="margin-bottom: 24px">
                  配置该服务商支持的核心能力。手动勾选后可辅助后续 AI 自动生成路由策略，或点击「自动探测能力」探查接口。
                </NAlert>
                <NGrid :cols="4" :x-gap="12" :y-gap="12" responsive="screen" item-responsive>
                  <NGridItem span="0:4 900:1">
                    <NFormItem label="Text Gen (对话)">
                      <NSwitch v-model:value="capTextGen" />
                      <NTag v-if="!capTextGen" type="error" size="small" style="margin-left: 12px">必备缺失</NTag>
                      <NTag v-else type="success" size="small" style="margin-left: 12px">满足</NTag>
                    </NFormItem>
                  </NGridItem>
                  <NGridItem span="0:4 900:1">
                    <NFormItem label="Embedding (向量)">
                      <NSwitch v-model:value="capEmbedding" />
                      <NTag v-if="!capEmbedding" type="error" size="small" style="margin-left: 12px">必备缺失</NTag>
                      <NTag v-else type="success" size="small" style="margin-left: 12px">满足</NTag>
                    </NFormItem>
                  </NGridItem>
                  <NGridItem span="0:4 900:1">
                    <NFormItem label="Image Gen (图片)">
                      <NSwitch v-model:value="capImageGen" />
                      <NTag v-if="!capImageGen" type="warning" size="small" style="margin-left: 12px">建议补充</NTag>
                    </NFormItem>
                  </NGridItem>
                  <NGridItem span="0:4 900:1">
                    <NFormItem label="Video Gen (视频)">
                      <NSwitch v-model:value="capVideoGen" />
                    </NFormItem>
                  </NGridItem>
                  <NGridItem span="0:4 900:1">
                    <NFormItem label="TTS (语音合成)">
                      <NSwitch v-model:value="capTts" />
                      <NTag v-if="!capTts" type="warning" size="small" style="margin-left: 12px">建议补充</NTag>
                    </NFormItem>
                  </NGridItem>
                  <NGridItem span="0:4 900:1">
                    <NFormItem label="STT (语音转化)">
                      <NSwitch v-model:value="capStt" />
                    </NFormItem>
                  </NGridItem>
                  <NGridItem span="0:4 900:1">
                    <NFormItem label="Multimodal (多模态)">
                      <NSwitch v-model:value="capMultimodal" />
                    </NFormItem>
                  </NGridItem>
                  <NGridItem span="0:4 900:1">
                    <NFormItem label="Tool Calling (函数)">
                      <NSwitch v-model:value="capToolCalling" />
                    </NFormItem>
                  </NGridItem>
                </NGrid>

                <NDivider />
                
                <NSpace align="center">
                  <NButton type="warning" secondary @click="onTestProvider" :loading="isProbing">🔄 连通性探测 (Probe)</NButton>
                </NSpace>
                
                <div v-show="providerProbeRows.length > 0" style="margin-top: 16px">
                  <NDataTable :columns="probeColumns" :data="providerProbeRows" :pagination="{ pageSize: 5 }" size="small" />
                </div>
              </div>
            </NTabPane>
          </NTabs>
        </NCard>

        <div v-else class="empty-detail">
          <NEmpty description="👈 请在左侧选择提供商进行配置，或点击新增" />
        </div>
      </div>
    </div>

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
  NPopconfirm,
  NSelect,
  NSpace,
  NSwitch,
  NTabPane,
  NTabs,
  NTag,
  NThing,
  type DataTableColumns,
} from "naive-ui";
import { useI18n } from "@/composables/useI18n";


import {
  deleteProvider,
  listProviders,
  testProviderConnection,
  upsertProvider,
  type ProviderConnectionTestResponse,
  type ProviderResponse,
} from "@/api/product";

const { t } = useI18n();

const tenantId = ref("default");
const projectId = ref("default");

const providerKeyword = ref("");
const providers = ref<ProviderResponse[]>([]);
const selectedProviderId = ref("");
const isAddingNew = ref(false);

const providerName = ref("");
const providerEndpoint = ref("");
const providerAuthMode = ref("api_key");
const providerToken = ref("");
const providerModelCatalogCsv = ref("");
const providerProbePath = ref("/models");
const providerProbeRows = ref<ProviderProbeRow[]>([]);

const capTextGen = ref(false);
const capEmbedding = ref(false);
const capMultimodal = ref(false);
const capImageGen = ref(false);
const capVideoGen = ref(false);
const capTts = ref(false);
const capStt = ref(false);
const capToolCalling = ref(false);

const message = ref("");
const errorMessage = ref("");
const isSaving = ref(false);
const isProbing = ref(false);

const authModeOptions = [
  { label: "API Key (Header)", value: "api_key" },
  { label: "Bearer Token", value: "bearer" },
  { label: "无鉴权 (None)", value: "none" },
];

interface ProviderProbeRow {
  provider_id: string;
  provider_name: string;
  connected: boolean;
  status_code: number | null;
  latency_ms: number | null;
  message: string;
  checked_at: string;
}

const filteredProviders = computed(() =>
  providers.value.filter((item: ProviderResponse) => {
    const keyword = providerKeyword.value.trim().toLowerCase();
    if (!keyword) return true;
    return item.name.toLowerCase().includes(keyword) || (item.endpoint || "").toLowerCase().includes(keyword);
  })
);

const probeColumns: DataTableColumns<ProviderProbeRow> = [
  { title: "Status", key: "connected", render: (row: ProviderProbeRow) => h(NTag, { type: row.connected ? 'success' : 'error', size: 'small' }, { default: () => row.connected ? 'OK' : 'FAIL' }) },
  { title: "HTTP Code", key: "status_code", render: (row: ProviderProbeRow) => String(row.status_code ?? "-") },
  { title: "Latency(ms)", key: "latency_ms", render: (row: ProviderProbeRow) => String(row.latency_ms ?? "-") },
  { title: "Message", key: "message" },
  { title: "Time", key: "checked_at", render: (row: ProviderProbeRow) => new Date(row.checked_at).toLocaleTimeString() },
];

function stringifyError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function clearNotice(): void {
  message.value = "";
  errorMessage.value = "";
}

async function onLoadProviders(): Promise<void> {
  clearNotice();
  try {
    providers.value = await listProviders(tenantId.value, projectId.value);
  } catch (error) {
    errorMessage.value = `加载服务商失败: ${stringifyError(error)}`;
  }
}

function onAddNewProvider() {
  clearNotice();
  selectedProviderId.value = "";
  isAddingNew.value = true;
  providerName.value = "new_provider";
  providerEndpoint.value = "https://...";
  providerAuthMode.value = "api_key";
  providerToken.value = "";
  providerModelCatalogCsv.value = "";
  providerProbeRows.value = [];
  capTextGen.value = false;
  capEmbedding.value = false;
  capMultimodal.value = false;
  capImageGen.value = false;
  capVideoGen.value = false;
  capTts.value = false;
  capStt.value = false;
  capToolCalling.value = false;
}

function onSelectProvider(prov: ProviderResponse) {
  clearNotice();
  isAddingNew.value = false;
  selectedProviderId.value = prov.id;
  providerName.value = prov.name;
  providerEndpoint.value = prov.endpoint || "";
  providerAuthMode.value = prov.auth_mode || "api_key";
  providerToken.value = ""; // Masked from backend
  providerModelCatalogCsv.value = (prov.model_catalog || []).join(", ");
  providerProbeRows.value = [];

  const caps = prov.capability_flags || {};
  capTextGen.value = Boolean(caps.supports_text_generation);
  capEmbedding.value = Boolean(caps.supports_embedding);
  capMultimodal.value = Boolean(caps.supports_multimodal);
  capImageGen.value = Boolean(caps.supports_image_generation);
  capVideoGen.value = Boolean(caps.supports_video_generation);
  capTts.value = Boolean(caps.supports_tts);
  capStt.value = Boolean(caps.supports_stt);
  capToolCalling.value = Boolean(caps.supports_tool_calling);
}

async function onUpsertProvider(): Promise<void> {
  clearNotice();
  if (!providerName.value || !providerEndpoint.value) {
    errorMessage.value = "必须填写 Provider Name 和 Endpoint。";
    return;
  }
  isSaving.value = true;
  try {
    const catalog = providerModelCatalogCsv.value
      .split(",")
      .map((item: string) => item.trim())
      .filter((item: string) => item.length > 0);

    const provider = await upsertProvider({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      name: providerName.value,
      endpoint: providerEndpoint.value,
      auth_mode: providerAuthMode.value,
      enabled: true,
      access_token: providerToken.value || undefined,
      model_catalog: catalog,
      capability_flags: {
        supports_text_generation: capTextGen.value,
        supports_embedding: capEmbedding.value,
        supports_multimodal: capMultimodal.value,
        supports_image_generation: capImageGen.value,
        supports_video_generation: capVideoGen.value,
        supports_tts: capTts.value,
        supports_stt: capStt.value,
        supports_tool_calling: capToolCalling.value,
      },
    });

    await onLoadProviders();
    onSelectProvider(providers.value.find((p: ProviderResponse) => p.id === provider.id)!);
    message.value = `Provider 配置已保存！`;
  } catch (error) {
    errorMessage.value = `保存失败: ${stringifyError(error)}`;
  } finally {
    isSaving.value = false;
  }
}

async function onDeleteProvider(providerId: string): Promise<void> {
  clearNotice();
  try {
    await deleteProvider(providerId, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
    });
    selectedProviderId.value = "";
    isAddingNew.value = false;
    await onLoadProviders();
    message.value = `Provider已被成功删除`;
  } catch (error) {
    errorMessage.value = `删除失败: ${stringifyError(error)}`;
  }
}

function toProbeRow(response: ProviderConnectionTestResponse): ProviderProbeRow {
  return {
    provider_id: response.provider_id,
    provider_name: response.provider_name,
    connected: response.connected,
    status_code: response.status_code ?? null,
    latency_ms: response.latency_ms ?? null,
    message: response.message,
    checked_at: new Date().toISOString(),
  };
}

async function onTestProvider(): Promise<void> {
  clearNotice();
  const targetProviderId = (selectedProviderId.value).trim();
  if (!targetProviderId) {
    errorMessage.value = "请先选中或保存 Provider 后再进行探测";
    return;
  }
  
  isProbing.value = true;
  try {
    const response = await testProviderConnection(targetProviderId, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      probe_path: providerProbePath.value || "/models",
      timeout_ms: 10000,
    });
    const row = toProbeRow(response);
    providerProbeRows.value = [row, ...providerProbeRows.value];
    if (response.connected) {
      message.value = `探测成功 (${response.status_code ?? "OK"})`;
    } else {
      errorMessage.value = `探测失败: ${response.message}`;
    }
  } catch (error) {
    errorMessage.value = `探测出错: ${stringifyError(error)}`;
  } finally {
    isProbing.value = false;
  }
}

onMounted(() => {
  void onLoadProviders();
});
</script>

<style scoped>
.page-grid {
  padding: 8px;
}

.provider-layout {
  display: grid;
  grid-template-columns: 280px 1fr;
  gap: 16px;
}

@media (max-width: 900px) {
  .provider-layout {
    grid-template-columns: 1fr;
  }
}

.provider-list-card {
  min-height: calc(100vh - 120px);
}

.active-item {
  background-color: var(--n-color-hover);
  border-left: 3px solid var(--n-primary-color);
}

.empty-detail {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: calc(100vh - 120px);
  background-color: var(--n-card-color);
  border-radius: 8px;
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
