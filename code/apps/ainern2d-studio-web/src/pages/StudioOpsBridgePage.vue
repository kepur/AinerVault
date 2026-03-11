<template>
  <div class="ops-page">
    <NCard title="AinerOps Open Ingress" size="small" class="scope-card">
      <NForm inline label-placement="left" :show-feedback="false">
        <NFormItem label="Tenant">
          <NInput v-model:value="tenantId" placeholder="default" />
        </NFormItem>
        <NFormItem label="Project">
          <NInput v-model:value="projectId" placeholder="default" />
        </NFormItem>
        <NFormItem>
          <NButton type="primary" :loading="loading" @click="reloadAll">刷新</NButton>
        </NFormItem>
      </NForm>
      <NDivider style="margin: 10px 0 8px;" />
      <NGrid :cols="3" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:3 1000:1">
          <NText depth="3">上报域名</NText>
          <div class="ingress-value">{{ opsIngressDomain || "-" }}</div>
        </NGridItem>
        <NGridItem span="0:3 1000:1">
          <NText depth="3">上报完整 URL</NText>
          <div class="ingress-value">{{ opsIngressReportUrl || "-" }}</div>
        </NGridItem>
        <NGridItem span="0:3 1000:1">
          <NText depth="3">URI 路径</NText>
          <div class="ingress-value">{{ opsIngressUri }}</div>
        </NGridItem>
      </NGrid>
      <NSpace style="margin-top: 8px;">
        <NButton size="small" @click="onCopyText(opsIngressDomain, '域名')">复制域名</NButton>
        <NButton size="small" @click="onCopyText(opsIngressReportUrl, '上报URL')">复制上报URL</NButton>
        <NButton size="small" @click="onCopyText(opsIngressUri, 'URI路径')">复制URI路径</NButton>
      </NSpace>
      <NAlert type="info" :bordered="false" style="margin-top: 8px;">
        地址来源：{{ opsIngressSourceLabel }}。若 AinerOps 不在同一 Docker 网络，请使用
        <code>host.docker.internal:8000</code> 或宿主机 IP:<code>8000</code>。
      </NAlert>
    </NCard>

    <NGrid :cols="2" :x-gap="12" :y-gap="12" responsive="screen" item-responsive>
      <NGridItem span="0:2 960:1">
        <NCard title="Ingress Token (90 days)" size="small" class="token-card">
          <NSpace vertical :size="10">
            <NAlert type="info" :bordered="false">
              Token 默认有效期 90 天。只有点击“重新生成”后旧 token 才会立即失效。
            </NAlert>
            <NForm label-placement="left" :label-width="110">
              <NFormItem label="Token">
                <NInput
                  :value="tokenVisible ? revealedToken : (tokenInfo?.token_masked || '')"
                  readonly
                  :type="tokenVisible ? 'text' : 'password'"
                  placeholder="点击显示"
                />
              </NFormItem>
              <NFormItem label="有效期至">
                <NText>{{ tokenInfo ? formatTime(tokenInfo.expires_at) : "-" }}</NText>
              </NFormItem>
              <NFormItem label="剩余天数">
                <NTag :type="(tokenInfo?.days_remaining || 0) > 7 ? 'success' : 'warning'" size="small" :bordered="false">
                  {{ tokenInfo?.days_remaining ?? "-" }} days
                </NTag>
              </NFormItem>
              <NFormItem label="最后使用">
                <NText>{{ tokenInfo?.last_used_at ? formatTime(tokenInfo.last_used_at) : "-" }}</NText>
              </NFormItem>
            </NForm>
            <NSpace>
              <NButton :loading="tokenLoading" @click="onToggleRevealToken">
                {{ tokenVisible ? "隐藏" : "显示 Token" }}
              </NButton>
              <NButton :loading="tokenLoading" @click="onCopyToken">复制</NButton>
              <NButton type="warning" :loading="tokenLoading" @click="onRegenerateToken">重新生成</NButton>
            </NSpace>
          </NSpace>
        </NCard>
      </NGridItem>

      <NGridItem span="0:2 960:1">
        <NCard title="MinIO / Object Storage" size="small" class="storage-card">
          <NSpace vertical :size="10">
            <NAlert type="info" :bordered="false">
              可直接在后台维护 MinIO 配置；保存后会同步更新运行时配置，并写回 code/.env，便于复制给其他系统。
            </NAlert>
            <NForm label-placement="left" :label-width="96">
              <NFormItem label="Provider">
                <div class="ingress-value">{{ storageConfig?.provider || "-" }}</div>
              </NFormItem>
              <NFormItem label="公开地址">
                <NInput
                  :value="storageForm.endpoint"
                  placeholder="http://localhost:9000"
                  @update:value="(value) => storageForm.endpoint = value"
                />
              </NFormItem>
              <NFormItem label="内部地址">
                <NInput
                  :value="storageForm.internal_endpoint"
                  placeholder="http://minio:9000"
                  @update:value="(value) => storageForm.internal_endpoint = value"
                />
              </NFormItem>
              <NFormItem label="Console">
                <NInput
                  :value="storageForm.console_endpoint"
                  placeholder="http://localhost:9001"
                  @update:value="(value) => storageForm.console_endpoint = value"
                />
              </NFormItem>
              <NFormItem label="Bucket">
                <NInput
                  :value="storageForm.bucket"
                  placeholder="ainer-assets"
                  @update:value="(value) => storageForm.bucket = value"
                />
              </NFormItem>
              <NFormItem label="Region">
                <NInput
                  :value="storageForm.region"
                  placeholder="us-east-1"
                  @update:value="(value) => storageForm.region = value"
                />
              </NFormItem>
              <NFormItem label="Access Key">
                <NInput
                  :value="storageForm.access_key"
                  placeholder="ainer_minio"
                  @update:value="(value) => storageForm.access_key = value"
                />
              </NFormItem>
              <NFormItem label="Secret Key">
                <NInput
                  type="password"
                  show-password-on="click"
                  :value="storageForm.secret_key"
                  placeholder="ainer_minio_2024"
                  @update:value="(value) => storageForm.secret_key = value"
                />
              </NFormItem>
              <NFormItem label="Root User">
                <NInput
                  :value="storageForm.root_user"
                  placeholder="ainer_minio"
                  @update:value="(value) => storageForm.root_user = value"
                />
              </NFormItem>
              <NFormItem label="Root Pass">
                <NInput
                  type="password"
                  show-password-on="click"
                  :value="storageForm.root_password"
                  placeholder="ainer_minio_2024"
                  @update:value="(value) => storageForm.root_password = value"
                />
              </NFormItem>
            </NForm>
            <NSpace wrap>
              <NButton type="primary" size="small" :loading="storageSaving" @click="onSaveStorageConfig">保存配置</NButton>
              <NButton size="small" :disabled="!storageDirty" @click="resetStorageForm">重置</NButton>
              <NButton size="small" @click="onCopyText(storageForm.endpoint || '', 'MinIO公开地址')">复制公开地址</NButton>
              <NButton size="small" @click="onCopyText(storageForm.internal_endpoint || '', 'MinIO内部地址')">复制内部地址</NButton>
              <NButton size="small" @click="onCopyText(storageForm.access_key || '', 'Access Key')">复制 Access Key</NButton>
              <NButton size="small" @click="onCopyText(storageForm.secret_key || '', 'Secret Key')">复制 Secret Key</NButton>
              <NButton size="small" @click="onCopyText(storageConfig?.copy_env_block || '', 'MinIO环境块')">复制环境块</NButton>
            </NSpace>
            <NText depth="3">保存后可直接复制给 AinerOps 或其他系统使用。</NText>
          </NSpace>
        </NCard>
      </NGridItem>

      <NGridItem span="0:2 960:1">
        <NCard title="Adapter Spec (Unified Contract)" size="small">
          <NAlert type="warning" :bordered="false" style="margin-bottom: 10px;">
            AinerOps 只上报原始地址/文档/能力。Studio 本地中间层负责自动解析文档并映射为统一键值，不把业务直接绑到厂商私有 API。
          </NAlert>
          <NCollapse>
            <NCollapseItem
              v-for="item in adapterSpecItems"
              :key="item.capability"
              :title="item.capability"
              :name="item.capability"
            >
              <NText depth="3">request_required</NText>
              <div class="spec-line">{{ item.requestRequired.join(", ") || "-" }}</div>
              <NText depth="3">response_required</NText>
              <div class="spec-line">{{ item.responseRequired.join(", ") || "-" }}</div>
              <NText depth="3">response_optional</NText>
              <div class="spec-line">{{ item.responseOptional.join(", ") || "-" }}</div>
            </NCollapseItem>
          </NCollapse>
        </NCard>
      </NGridItem>
    </NGrid>

    <NCard title="Local Capability Standard (High / Medium / Low)" size="small" style="margin-top: 12px;">
      <NDataTable
        :columns="capabilityColumns"
        :data="capabilityRows"
        :pagination="{ pageSize: 8 }"
        size="small"
        :bordered="false"
      />
    </NCard>

    <NCard title="Requirement Negotiation / Auto Integration" size="small" style="margin-top: 12px;">
      <NGrid :cols="2" :x-gap="12" :y-gap="12" responsive="screen" item-responsive>
        <NGridItem span="0:2 960:1">
          <NSpace vertical :size="10">
            <NAlert type="info" :bordered="false">
              这里可直接模拟 AinerOps 需求协商：输入目标能力、档位、约束与偏好后，Studio 会生成 RoutePlan / GapReport，并可一键固化为可回滚的对接版本。
            </NAlert>
            <NForm label-placement="left" :label-width="112">
              <NFormItem label="能力类型">
                <NSelect
                  :value="planForm.capability"
                  :options="requirementCapabilityOptions"
                  placeholder="请选择能力"
                  filterable
                  clearable
                  @update:value="(value) => { planForm.capability = String(value || ''); void reloadIntegrations(); }"
                />
              </NFormItem>
              <NFormItem label="目标档位">
                <NSelect
                  :value="planForm.tier"
                  :options="tierOptions"
                  @update:value="onUpdatePlanTier"
                />
              </NFormItem>
              <NFormItem label="必需特性">
                <NInput
                  :value="planForm.requiredFeaturesText"
                  type="textarea"
                  :rows="3"
                  placeholder="多值可使用逗号或换行分隔，如&#10;streaming&#10;image_to_video"
                  @update:value="(value) => planForm.requiredFeaturesText = value"
                />
              </NFormItem>
              <NFormItem label="约束(JSON)">
                <NInput
                  :value="planForm.constraintsText"
                  type="textarea"
                  :rows="5"
                  @update:value="(value) => planForm.constraintsText = value"
                />
              </NFormItem>
              <NFormItem label="偏好(JSON)">
                <NInput
                  :value="planForm.preferencesText"
                  type="textarea"
                  :rows="5"
                  @update:value="(value) => planForm.preferencesText = value"
                />
              </NFormItem>
            </NForm>
            <NSpace>
              <NButton type="primary" :loading="planLoading" @click="onCreatePlan">一键自动对接</NButton>
              <NButton :loading="integrationLoading" @click="reloadIntegrations">刷新版本列表</NButton>
              <NButton @click="reloadRequirementConfig">刷新协商Schema</NButton>
            </NSpace>
          </NSpace>
        </NGridItem>

        <NGridItem span="0:2 960:1">
          <NSpace vertical :size="10">
            <div class="plan-panel">
              <div class="plan-panel__title">当前能力要求</div>
              <div class="plan-panel__line">
                aliases: {{ selectedRequirementDefinition?.aliases?.join(", ") || "-" }}
              </div>
              <div class="plan-panel__line">
                must_support: {{ selectedRequirementTier?.must_support?.join(", ") || "-" }}
              </div>
              <div class="plan-panel__line">
                optional_support: {{ selectedRequirementTier?.optional_support?.join(", ") || "-" }}
              </div>
              <div class="plan-panel__line">
                target_values: {{ JSON.stringify(selectedRequirementTier?.target_values || {}, null, 2) }}
              </div>
            </div>

            <div class="plan-panel">
              <div class="plan-panel__title">最新协商结果</div>
              <div class="plan-panel__line">status: {{ latestPlan?.status || "-" }}</div>
              <div class="plan-panel__line">route_plan: {{ routePlanSummary(latestPlan?.route_plan) }}</div>
              <div class="plan-panel__line">gap_report: {{ gapSummary(latestPlan?.gap_report) }}</div>
              <div class="plan-panel__line">
                candidates_considered: {{ latestPlan?.candidates_considered ?? "-" }}
              </div>
              <div class="plan-panel__line">
                integration_version: {{ latestPlan?.integration ? `v${latestPlan.integration.version} / ${latestPlan.integration.status}` : "-" }}
              </div>
            </div>

            <div class="plan-panel">
              <div class="plan-panel__title">协商 Schema 版本</div>
              <div class="plan-panel__line">schema_version: {{ requirementSchema?.schema_version || "-" }}</div>
              <div class="plan-panel__line">
                tier_aliases: {{ Object.keys(requirementSchema?.tier_aliases || {}).join(", ") || "-" }}
              </div>
            </div>
          </NSpace>
        </NGridItem>
      </NGrid>

      <div v-if="displayCapabilityStats.length" class="capability-stats-grid">
        <div v-for="item in displayCapabilityStats" :key="item.capability_type" class="capability-stat-card">
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
            <div>最近时间：{{ item.latest_at ? formatTime(item.latest_at) : '-' }}</div>
          </div>
        </div>
      </div>

      <NDivider style="margin: 12px 0;" />

      <NDataTable
        :columns="integrationColumns"
        :data="integrationRows"
        :loading="integrationLoading"
        :pagination="{ pageSize: 6 }"
        size="small"
        :bordered="false"
        :scroll-x="900"
      />
    </NCard>

    <NCard title="Reported Providers (AinerOps)" size="small" style="margin-top: 12px;">
      <template #header-extra>
        <NSpace>
          <NSelect
            v-model:value="statusFilter"
            :options="statusOptions"
            clearable
            style="width: 170px;"
            placeholder="全部状态"
            @update:value="reloadProviders"
          />
          <NSelect
            v-model:value="capabilityFilter"
            :options="capabilityFilterOptions"
            clearable
            filterable
            style="width: 220px;"
            placeholder="全部能力"
            @update:value="reloadProviders"
          />
        </NSpace>
      </template>
      <NDataTable
        :columns="providerColumns"
        :data="providerRows"
        :loading="providerLoading"
        :pagination="{ pageSize: 10 }"
        size="small"
        :bordered="false"
        :scroll-x="2200"
      />
    </NCard>

    <NModal v-model:show="mappingModalVisible" preset="card" title="映射详情" style="width: 780px;">
      <pre class="mapping-detail">{{ mappingDetailText(mappingModalRow) }}</pre>
    </NModal>

    <NModal v-model:show="quickRunModalVisible" preset="card" title="快速试调用结果" style="width: 780px;">
      <div v-if="quickRunResult" class="quickrun-stack">
        <div class="quickrun-summary-grid">
          <div class="quickrun-tile">
            <div class="quickrun-tile__label">模式</div>
            <div class="quickrun-tile__value">{{ quickRunResult.mode }}</div>
          </div>
          <div class="quickrun-tile">
            <div class="quickrun-tile__label">能力</div>
            <div class="quickrun-tile__value">{{ quickRunResult.integration.capability_type }}</div>
          </div>
          <div class="quickrun-tile">
            <div class="quickrun-tile__label">Provider</div>
            <div class="quickrun-tile__value">{{ quickRunResult.integration.provider_name }}</div>
          </div>
          <div class="quickrun-tile">
            <div class="quickrun-tile__label">Profile</div>
            <div class="quickrun-tile__value">{{ quickRunResult.profile_name || '-' }}</div>
          </div>
        </div>

        <div class="quickrun-panel">
          <div class="quickrun-panel__title">联通探测</div>
          <div class="quickrun-panel__line">status: {{ quickRunProbe.status || '-' }}</div>
          <div class="quickrun-panel__line">detail: {{ quickRunProbe.detail || '-' }}</div>
          <div class="quickrun-panel__line">latency_ms: {{ quickRunProbe.latency_ms ?? '-' }}</div>
        </div>

        <div class="quickrun-panel">
          <div class="quickrun-panel__title">真实调用摘要</div>
          <div class="quickrun-panel__line">ok: {{ quickRunLiveResponse.ok ?? '-' }}</div>
          <div class="quickrun-panel__line">status_code: {{ quickRunLiveResponse.status_code ?? '-' }}</div>
          <div class="quickrun-panel__line">detail: {{ quickRunLiveResponse.detail || '-' }}</div>
        </div>

        <div class="quickrun-panel">
          <div class="quickrun-panel__title">请求预览</div>
          <pre class="mapping-detail">{{ JSON.stringify(quickRunResult.request_preview || {}, null, 2) }}</pre>
        </div>

        <div class="quickrun-panel">
          <div class="quickrun-panel__title">真实响应体</div>
          <pre class="mapping-detail">{{ JSON.stringify(quickRunLiveResponse.body || quickRunLiveResponse || {}, null, 2) }}</pre>
        </div>
      </div>
      <div v-else class="quickrun-empty">-</div>
    </NModal>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, reactive, ref } from "vue";
import {
  NAlert,
  NButton,
  NCard,
  NCollapse,
  NCollapseItem,
  NDataTable,
  NDivider,
  NForm,
  NFormItem,
  NGrid,
  NGridItem,
  NInput,
  NModal,
  NSelect,
  NSpace,
  NTag,
  NText,
  useMessage,
  type DataTableColumns,
  type SelectOption,
} from "naive-ui";

import {
  applyOpsRuntimeRouting,
  autoBindOpsProvider,
  createOpsPlan,
  getOpsRuntimeRouting,
  getRequirementSchema,
  getRequirementTiers,
  getOpsAdapterSpec,
  getOpsCapabilityStandards,
  getOpsStorageConfig,
  getOpsToken,
  listOpsIntegrations,
  listOpsProviders,
  listProviders,
  manualBindOpsProvider,
  quickRunOpsIntegration,
  regenerateOpsToken,
  rollbackOpsIntegration,
  revealOpsToken,
  testOpsProvider,
  updateOpsStorageConfig,
  type AdapterSpecResponse,
  type CapabilityStandardItem,
  type CapabilityRequirementDefinition,
  type OpsGapReport,
  type OpsIntegrationVersion,
  type OpsPlanResponse,
  type OpsProviderRow,
  type QuickRunResponse,
  type OpsRoutePlan,
  type OpsStorageConfigResponse,
  type OpsStorageConfigUpdatePayload,
  type OpsTokenResponse,
  type ProviderResponse,
  type RuntimeCapabilityStatResponse,
  type RequirementSchemaResponse,
  type RequirementTiersResponse,
} from "@/api/product";

const message = useMessage();

const tenantId = ref("default");
const projectId = ref("default");

const loading = ref(false);
const tokenLoading = ref(false);
const providerLoading = ref(false);
const storageSaving = ref(false);
const planLoading = ref(false);
const integrationLoading = ref(false);
const rollbackLoadingId = ref<string | null>(null);
const runtimeApplyLoadingId = ref<string | null>(null);
const promoteRuntimeLoadingId = ref<string | null>(null);
const quickRunLoadingId = ref<string | null>(null);

const tokenInfo = ref<OpsTokenResponse | null>(null);
const tokenVisible = ref(false);
const revealedToken = ref("");
const storageConfig = ref<OpsStorageConfigResponse | null>(null);
const requirementTiers = ref<RequirementTiersResponse | null>(null);
const requirementSchema = ref<RequirementSchemaResponse | null>(null);
const latestPlan = ref<OpsPlanResponse | null>(null);
const integrationRows = ref<OpsIntegrationVersion[]>([]);
const runtimeCapabilityStats = ref<RuntimeCapabilityStatResponse[]>([]);
const quickRunResult = ref<QuickRunResponse | null>(null);
const quickRunModalVisible = ref(false);
const storageForm = reactive<OpsStorageConfigUpdatePayload>({
  endpoint: "",
  internal_endpoint: "",
  console_endpoint: "",
  bucket: "",
  region: "us-east-1",
  access_key: "",
  secret_key: "",
  root_user: "",
  root_password: "",
});
const planForm = reactive({
  capability: "",
  tier: "standard" as "basic" | "standard" | "advanced",
  requiredFeaturesText: "",
  constraintsText: '{\n  "max_latency_ms": 12000\n}',
  preferencesText: '{\n  "prefer_connected": true\n}',
  autoIntegrate: true,
  validateConnectivity: true,
});

const capabilityRows = ref<CapabilityStandardItem[]>([]);
const adapterSpec = ref<AdapterSpecResponse | null>(null);

const providerRows = ref<OpsProviderRow[]>([]);
const providerCatalog = ref<ProviderResponse[]>([]);
const manualBindSelection = reactive<Record<string, string | null>>({});

const statusFilter = ref<string | null>(null);
const capabilityFilter = ref<string | null>(null);
const mappingModalVisible = ref(false);
const mappingModalRow = ref<OpsProviderRow | null>(null);
const opsIngressUri = "/api/v1/ops-bridge/report";

function isAbsoluteHttpUrl(value: string): boolean {
  return /^https?:\/\//i.test(value);
}

function normalizeBaseUrl(value: string): string {
  return value.replace(/\/+$/, "");
}

function localDockerHostFallback(): string {
  if (typeof window === "undefined") return "http://host.docker.internal:8000";
  const hostname = window.location.hostname.toLowerCase();
  if (hostname === "localhost" || hostname === "127.0.0.1" || hostname === "0.0.0.0") {
    return "http://host.docker.internal:8000";
  }
  return `${window.location.protocol}//${window.location.hostname}:8000`;
}

const opsIngressDomain = computed(() => {
  const publicBase = String(import.meta.env.VITE_OPS_BRIDGE_PUBLIC_BASE_URL || "").trim();
  if (publicBase && isAbsoluteHttpUrl(publicBase)) {
    return normalizeBaseUrl(publicBase);
  }
  const apiBase = String(import.meta.env.VITE_API_BASE_URL || "").trim();
  if (apiBase && isAbsoluteHttpUrl(apiBase)) {
    return normalizeBaseUrl(apiBase);
  }
  const proxyTarget = String(import.meta.env.VITE_PROXY_TARGET || "").trim();
  if (proxyTarget && isAbsoluteHttpUrl(proxyTarget)) {
    const normalized = normalizeBaseUrl(proxyTarget);
    if (normalized.includes("studio-api")) {
      return localDockerHostFallback();
    }
    return normalized;
  }
  if (typeof window === "undefined") {
    return "http://host.docker.internal:8000";
  }
  return localDockerHostFallback();
});

const opsIngressReportUrl = computed(() => {
  if (!opsIngressDomain.value) return "";
  return `${opsIngressDomain.value}${opsIngressUri}`;
});

const opsIngressSourceLabel = computed(() => {
  const publicBase = String(import.meta.env.VITE_OPS_BRIDGE_PUBLIC_BASE_URL || "").trim();
  if (publicBase && isAbsoluteHttpUrl(publicBase)) {
    return "VITE_OPS_BRIDGE_PUBLIC_BASE_URL";
  }
  const apiBase = String(import.meta.env.VITE_API_BASE_URL || "").trim();
  if (apiBase && isAbsoluteHttpUrl(apiBase)) {
    return "VITE_API_BASE_URL";
  }
  const proxyTarget = String(import.meta.env.VITE_PROXY_TARGET || "").trim();
  if (proxyTarget && isAbsoluteHttpUrl(proxyTarget)) {
    return "VITE_PROXY_TARGET + Docker fallback";
  }
  return "Docker fallback";
});

const statusOptions: SelectOption[] = [
  { label: "已对接", value: "integrated" },
  { label: "未对接", value: "unbound" },
  { label: "能力/映射不足", value: "capability_gap" },
];

const capabilityFilterOptions = computed<SelectOption[]>(() =>
  capabilityRows.value.map((item) => ({
    label: `${item.display_name} (${item.capability_type})`,
    value: item.capability_type,
  })),
);

const providerOptions = computed<SelectOption[]>(() =>
  providerCatalog.value.map((item) => ({
    label: item.name,
    value: item.id,
  })),
);

const adapterSpecItems = computed(() => {
  if (!adapterSpec.value?.items) return [];
  return Object.entries(adapterSpec.value.items).map(([capability, spec]: [string, AdapterSpecResponse["items"][string]]) => ({
    capability,
    requestRequired: spec.request_required || [],
    responseRequired: spec.response_required || [],
    responseOptional: spec.response_optional || [],
  }));
});

const requirementCapabilityOptions = computed<SelectOption[]>(() =>
  (requirementTiers.value?.items || []).map((item) => ({
    label: `${item.display_name} (${item.capability_type})`,
    value: item.capability_type,
  })),
);

const selectedRequirementDefinition = computed<CapabilityRequirementDefinition | null>(() =>
  (requirementTiers.value?.items || []).find((item) => item.capability_type === planForm.capability) || null,
);

const selectedRequirementTier = computed(() =>
  selectedRequirementDefinition.value?.tiers?.[planForm.tier] || null,
);

const displayCapabilityStats = computed(() => {
  const items = runtimeCapabilityStats.value || [];
  if (!planForm.capability) {
    return items;
  }
  const filtered = items.filter((item) => item.capability_type === planForm.capability);
  return filtered.length ? filtered : items;
});

const quickRunProbe = computed<Record<string, unknown>>(() =>
  (quickRunResult.value?.probe as Record<string, unknown> | undefined) || {},
);

const quickRunLiveResponse = computed<Record<string, unknown>>(() =>
  (quickRunResult.value as unknown as { live_response?: Record<string, unknown> } | null)?.live_response || {},
);

const tierOptions: SelectOption[] = [
  { label: "Basic", value: "basic" },
  { label: "Standard", value: "standard" },
  { label: "Advanced", value: "advanced" },
];

const storageDirty = computed(() => {
  if (!storageConfig.value) return false;
  return [
    storageConfig.value.endpoint !== storageForm.endpoint,
    storageConfig.value.internal_endpoint !== storageForm.internal_endpoint,
    (storageConfig.value.console_endpoint || "") !== (storageForm.console_endpoint || ""),
    storageConfig.value.bucket !== storageForm.bucket,
    storageConfig.value.region !== storageForm.region,
    storageConfig.value.access_key !== storageForm.access_key,
    storageConfig.value.secret_key !== storageForm.secret_key,
    storageConfig.value.root_user !== storageForm.root_user,
    storageConfig.value.root_password !== storageForm.root_password,
  ].some(Boolean);
});

const integrationColumns = computed<DataTableColumns<OpsIntegrationVersion>>(() => [
  {
    title: "Capability",
    key: "capability_type",
    width: 180,
    render: (row) =>
      h("div", [
        h("div", { style: "font-weight:600;" }, row.capability_type),
        h("div", { style: "font-size:12px;color:#666;" }, `tier: ${String(row.tier).toUpperCase()}`),
      ]),
  },
  {
    title: "Provider",
    key: "provider_name",
    width: 220,
    render: (row) =>
      h("div", [
        h("div", { style: "font-weight:600;" }, row.provider_name),
        h("div", { style: "font-size:12px;color:#666;" }, row.provider_key),
      ]),
  },
  {
    title: "Version",
    key: "version",
    width: 90,
  },
  {
    title: "Status",
    key: "status",
    width: 120,
    render: (row) =>
      h(
        NTag,
        {
          bordered: false,
          size: "small",
          type: row.status === "active" ? "success" : "default",
        },
        { default: () => row.status },
      ),
  },
  {
    title: "Mapping",
    key: "mapping_status",
    width: 120,
    render: (row) =>
      h(
        NTag,
        {
          bordered: false,
          size: "small",
          type: row.mapping_status === "mapped" ? "success" : row.mapping_status === "partial" ? "warning" : "error",
        },
        { default: () => row.mapping_status },
      ),
  },
  {
    title: "Created",
    key: "created_at",
    width: 180,
    render: (row) => (row.created_at ? formatTime(row.created_at) : "-"),
  },
  {
    title: "最近状态/耗时",
    key: "latest_runtime_status",
    width: 180,
    render: (row) => {
      const stat = runtimeCapabilityStats.value.find((item) => item.capability_type === row.capability_type);
      if (!stat) {
        return "-";
      }
      const statusLabel = stat.latest_status === "success"
        ? "成功"
        : stat.latest_status === "failed"
          ? "失败"
          : "暂无记录";
      const latencyLabel = formatLatency(stat.latest_latency_ms);
      return h("div", [
        h(
          NTag,
          {
            bordered: false,
            size: "small",
            type: stat.latest_status === "success" ? "success" : stat.latest_status === "failed" ? "error" : "default",
          },
          { default: () => statusLabel },
        ),
        h("div", { style: "font-size:12px;color:#666;margin-top:4px;" }, latencyLabel),
      ]);
    },
  },
  {
    title: "Actions",
    key: "actions",
    width: 320,
    render: (row) =>
      h(NSpace, { size: 6 }, () => [
        h(
          NButton,
          {
            size: "small",
            type: "warning",
            loading: promoteRuntimeLoadingId.value === row.integration_id,
            onClick: () => onPromoteAndApplyRuntimeRouting(row),
          },
          { default: () => "设主并写路由" },
        ),
        h(
          NButton,
          {
            size: "small",
            type: "primary",
            loading: runtimeApplyLoadingId.value === row.integration_id,
            onClick: () => onApplyRuntimeRouting(row),
          },
          { default: () => "写入运行时路由" },
        ),
        h(
          NButton,
          {
            size: "small",
            loading: quickRunLoadingId.value === row.integration_id,
            onClick: () => onQuickRunIntegration(row),
          },
          { default: () => "快速试调用" },
        ),
        h(
          NButton,
          {
            size: "small",
            disabled: row.status === "active" || rollbackLoadingId.value === row.integration_id,
            loading: rollbackLoadingId.value === row.integration_id,
            onClick: () => onRollbackIntegration(row),
          },
          { default: () => "回滚到此版本" },
        ),
      ]),
  },
]);

const capabilityColumns = computed<DataTableColumns<CapabilityStandardItem>>(() => [
  {
    title: "Capability",
    key: "capability_type",
    width: 220,
    render: (row) =>
      h("div", [
        h("div", { style: "font-weight:600;" }, row.display_name),
        h("div", { style: "font-size:12px;color:#666;" }, row.capability_type),
      ]),
  },
  {
    title: "Track Targets",
    key: "track_targets",
    width: 180,
    render: (row) => row.track_targets.join(", "),
  },
  {
    title: "LOW",
    key: "low",
    render: (row) => row.tiers.low.join(", "),
  },
  {
    title: "MEDIUM",
    key: "medium",
    render: (row) => row.tiers.medium.join(", "),
  },
  {
    title: "HIGH",
    key: "high",
    render: (row) => row.tiers.high.join(", "),
  },
]);

const providerColumns = computed<DataTableColumns<OpsProviderRow>>(() => [
  {
    title: "Provider",
    key: "provider_name",
    width: 210,
    render: (row) =>
      h("div", [
        h("div", { style: "font-weight:600;" }, row.provider_name),
        h("div", { style: "font-size:12px;color:#666;" }, row.provider_key),
      ]),
  },
  {
    title: "Capability",
    key: "capability_type",
    width: 180,
  },
  {
    title: "Tier",
    key: "capability_tier",
    width: 130,
    render: (row) =>
      h(
        NTag,
        {
          bordered: false,
          type: row.capability_tier === "high" ? "success" : row.capability_tier === "medium" ? "info" : row.capability_tier === "low" ? "warning" : "error",
          size: "small",
        },
        { default: () => `${row.capability_tier.toUpperCase()} / min:${row.min_required_tier.toUpperCase()}` },
      ),
  },
  {
    title: "Status",
    key: "integration_status",
    width: 140,
    render: (row) =>
      h(
        NTag,
        {
          bordered: false,
          size: "small",
          type: row.integration_status === "integrated" ? "success" : row.integration_status === "capability_gap" ? "warning" : "default",
        },
        { default: () => row.integration_status_label },
      ),
  },
  {
    title: "Matched Provider",
    key: "matched_provider_name",
    width: 180,
    render: (row) => row.matched_provider_name || "—",
  },
  {
    title: "Mapping",
    key: "mapping_status",
    width: 260,
    render: (row) =>
      h("div", [
        h(
          NTag,
          {
            bordered: false,
            size: "small",
            type:
              row.mapping_status === "mapped"
                ? "success"
                : row.mapping_status === "partial"
                  ? "warning"
                  : row.mapping_status === "failed"
                    ? "error"
                    : "default",
          },
          {
            default: () =>
              `${row.mapping_status}${row.mapping_confidence != null ? ` (${Math.round(row.mapping_confidence * 100)}%)` : ""}`,
          },
        ),
        h(
          "div",
          { style: "font-size:12px;color:#666;margin-top:4px;" },
          `req ${formatCoverage(row.request_coverage)} / resp ${formatCoverage(row.response_coverage)} / feat ${formatCoverage(row.feature_coverage)}`,
        ),
        row.mapping_gaps?.length
          ? h(
              "div",
              {
                style:
                  "font-size:11px;color:#999;margin-top:2px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;",
                title: row.mapping_gaps.join(", "),
              },
              row.mapping_gaps.join(", "),
            )
          : null,
      ]),
  },
  {
    title: "Connectivity",
    key: "connectivity_status",
    width: 210,
    render: (row) =>
      h("div", [
        h(
          NTag,
          {
            bordered: false,
            size: "small",
            type:
              row.connectivity_status === "connected"
                ? "success"
                : row.connectivity_status === "disconnected"
                  ? "error"
                  : "default",
          },
          { default: () => row.connectivity_label || "未测试" },
        ),
        h(
          "div",
          { style: "font-size:12px;color:#666;margin-top:4px;" },
          row.last_latency_ms != null ? `${row.last_latency_ms} ms` : "—",
        ),
      ]),
  },
  {
    title: "Last Report",
    key: "last_reported_at",
    width: 170,
    render: (row) => (row.last_reported_at ? formatTime(row.last_reported_at) : "-"),
  },
  {
    title: "Actions",
    key: "actions",
    width: 620,
    render: (row) =>
      h(NSpace, { size: 6 }, () => [
        h(
          NButton,
          {
            size: "small",
            onClick: () => onAutoBind(row),
          },
          { default: () => "AI自动对接" },
        ),
        h(
          NButton,
          {
            size: "small",
            onClick: () => onTestProvider(row),
          },
          { default: () => "测试" },
        ),
        h(
          NButton,
          {
            size: "small",
            onClick: () => onShowMapping(row),
          },
          { default: () => "映射详情" },
        ),
        h(NSelect, {
          size: "small",
          style: "width: 170px",
          options: providerOptions.value,
          value: manualBindSelection[row.report_id] ?? row.matched_provider_id ?? null,
          clearable: true,
          placeholder: "手动对接",
          onUpdateValue: (value) => {
            manualBindSelection[row.report_id] = (value as string | null) ?? null;
          },
        }),
        h(
          NButton,
          {
            size: "small",
            type: "primary",
            onClick: () => onManualBind(row),
          },
          { default: () => "保存对接" },
        ),
      ]),
  },
]);

function formatTime(value: string): string {
  const time = new Date(value);
  if (Number.isNaN(time.getTime())) return value;
  return time.toLocaleString();
}

function formatCoverage(value?: number | null): string {
  if (value == null || Number.isNaN(value)) return "-";
  return `${Math.round(Number(value) * 100)}%`;
}

function formatLatency(value?: number | null): string {
  return typeof value === "number" && Number.isFinite(value) ? `${value} ms` : "-";
}

function formatSuccessRate(rate?: number | null, totalRuns?: number | null): string {
  if (!totalRuns) return "-";
  const normalized = typeof rate === "number" && Number.isFinite(rate) ? rate : 0;
  return `${normalized.toFixed(1)}%`;
}

function onShowMapping(row: OpsProviderRow): void {
  mappingModalRow.value = row;
  mappingModalVisible.value = true;
}

function mappingDetailText(row: OpsProviderRow | null): string {
  if (!row) return "";
  return [
    `provider: ${row.provider_name} (${row.provider_key})`,
    `capability: ${row.capability_type}`,
    `mapping_status: ${row.mapping_status}`,
    `mapping_confidence: ${row.mapping_confidence ?? "-"}`,
    `request_coverage: ${formatCoverage(row.request_coverage)}`,
    `response_coverage: ${formatCoverage(row.response_coverage)}`,
    `feature_coverage: ${formatCoverage(row.feature_coverage)}`,
    `mapping_generated_at: ${row.mapping_generated_at ? formatTime(row.mapping_generated_at) : "-"}`,
    `mapping_gaps: ${row.mapping_gaps?.length ? row.mapping_gaps.join(", ") : "-"}`,
    `connectivity: ${row.connectivity_label} (${row.connectivity_status})`,
    `checked_url: ${row.last_checked_url || "-"}`,
    `last_latency_ms: ${row.last_latency_ms ?? "-"}`,
    `last_detail: ${row.last_connectivity_detail || "-"}`,
  ].join("\n");
}

async function reloadAll(): Promise<void> {
  loading.value = true;
  try {
    await Promise.all([
      reloadToken(),
      reloadStorageConfig(),
      reloadRequirementConfig(),
      reloadCapabilities(),
      reloadIntegrations(),
      reloadRuntimeStats(),
      reloadProviders(),
    ]);
  } finally {
    loading.value = false;
  }
}

function normalizeRequirementFeatures(value: string): string[] {
  return value
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function onUpdatePlanTier(value: string | number | null): void {
  if (value === "basic" || value === "standard" || value === "advanced") {
    planForm.tier = value;
    return;
  }
  planForm.tier = "standard";
}

function parseJsonObjectInput(value: string, label: string): Record<string, unknown> {
  const trimmed = value.trim();
  if (!trimmed) return {};
  try {
    const parsed = JSON.parse(trimmed);
    if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") {
      throw new Error(`${label} 必须是 JSON 对象`);
    }
    return parsed as Record<string, unknown>;
  } catch (error) {
    throw new Error(`${label} 解析失败: ${String(error)}`);
  }
}

function routePlanSummary(routePlan?: OpsRoutePlan | null): string {
  if (!routePlan) return "-";
  return [
    `provider=${routePlan.selected_provider_name}`,
    `template=${routePlan.selected_template_id}@${routePlan.selected_template_version}`,
    `mapping=${routePlan.mapping_status}`,
  ].join(" / ");
}

function gapSummary(gapReport?: OpsGapReport | null): string {
  if (!gapReport) return "-";
  return `${gapReport.summary}${gapReport.missing_features?.length ? ` / missing: ${gapReport.missing_features.join(", ")}` : ""}`;
}

async function reloadRequirementConfig(): Promise<void> {
  try {
    const [tiersResp, schemaResp] = await Promise.all([
      getRequirementTiers(),
      getRequirementSchema(),
    ]);
    requirementTiers.value = tiersResp;
    requirementSchema.value = schemaResp;
    if (!planForm.capability && tiersResp.items.length) {
      planForm.capability = tiersResp.items[0]?.capability_type || "";
    }
  } catch (error) {
    message.error(`加载需求协商配置失败: ${String(error)}`);
  }
}

async function reloadIntegrations(): Promise<void> {
  integrationLoading.value = true;
  try {
    const resp = await listOpsIntegrations({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      capability_type: planForm.capability || undefined,
    });
    integrationRows.value = resp.items;
  } catch (error) {
    message.error(`加载自动对接版本失败: ${String(error)}`);
  } finally {
    integrationLoading.value = false;
  }
}

async function reloadRuntimeStats(): Promise<void> {
  try {
    const resp = await getOpsRuntimeRouting({
      tenant_id: tenantId.value,
      project_id: projectId.value,
    });
    runtimeCapabilityStats.value = resp.capability_stats || [];
  } catch (error) {
    message.error(`加载 quick-run 统计失败: ${String(error)}`);
  }
}

async function reloadStorageConfig(): Promise<void> {
  try {
    storageConfig.value = await getOpsStorageConfig();
    resetStorageForm();
  } catch (error) {
    message.error(`加载 MinIO 配置失败: ${String(error)}`);
  }
}

function resetStorageForm(): void {
  storageForm.endpoint = storageConfig.value?.endpoint || "";
  storageForm.internal_endpoint = storageConfig.value?.internal_endpoint || "";
  storageForm.console_endpoint = storageConfig.value?.console_endpoint || "";
  storageForm.bucket = storageConfig.value?.bucket || "";
  storageForm.region = storageConfig.value?.region || "us-east-1";
  storageForm.access_key = storageConfig.value?.access_key || "";
  storageForm.secret_key = storageConfig.value?.secret_key || "";
  storageForm.root_user = storageConfig.value?.root_user || "";
  storageForm.root_password = storageConfig.value?.root_password || "";
}

async function onSaveStorageConfig(): Promise<void> {
  storageSaving.value = true;
  try {
    storageConfig.value = await updateOpsStorageConfig({
      endpoint: storageForm.endpoint,
      internal_endpoint: storageForm.internal_endpoint,
      console_endpoint: storageForm.console_endpoint,
      bucket: storageForm.bucket,
      region: storageForm.region,
      access_key: storageForm.access_key,
      secret_key: storageForm.secret_key,
      root_user: storageForm.root_user,
      root_password: storageForm.root_password,
    });
    resetStorageForm();
    message.success("MinIO 配置已保存");
  } catch (error) {
    message.error(`保存 MinIO 配置失败: ${String(error)}`);
  } finally {
    storageSaving.value = false;
  }
}

async function onCreatePlan(): Promise<void> {
  if (!planForm.capability) {
    message.warning("请先选择能力类型");
    return;
  }
  planLoading.value = true;
  try {
    latestPlan.value = await createOpsPlan({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      capability: planForm.capability,
      tier: planForm.tier,
      required_features: normalizeRequirementFeatures(planForm.requiredFeaturesText),
      constraints: parseJsonObjectInput(planForm.constraintsText, "约束条件"),
      preferences: parseJsonObjectInput(planForm.preferencesText, "偏好配置"),
      auto_integrate: planForm.autoIntegrate,
      validate_connectivity: planForm.validateConnectivity,
      initiated_by: "studio_ops_bridge",
    });
    await Promise.all([reloadIntegrations(), reloadProviders()]);
    await reloadRuntimeStats();
    if (latestPlan.value.status === "planned") {
      message.success("自动对接方案已生成");
    } else {
      message.warning("已生成 Gap Report，请按建议补齐能力");
    }
  } catch (error) {
    message.error(`生成自动对接方案失败: ${String(error)}`);
  } finally {
    planLoading.value = false;
  }
}

async function onRollbackIntegration(row: OpsIntegrationVersion): Promise<void> {
  rollbackLoadingId.value = row.integration_id;
  try {
    const resp = await rollbackOpsIntegration(row.integration_id, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
    });
    await Promise.all([reloadIntegrations(), reloadProviders(), reloadRuntimeStats()]);
    message.success(`已回滚到版本 v${resp.integration.version}`);
  } catch (error) {
    message.error(`版本回滚失败: ${String(error)}`);
  } finally {
    rollbackLoadingId.value = null;
  }
}

async function onApplyRuntimeRouting(row: OpsIntegrationVersion): Promise<void> {
  runtimeApplyLoadingId.value = row.integration_id;
  try {
    await applyOpsRuntimeRouting({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      integration_id: row.integration_id,
    });
    await reloadRuntimeStats();
    message.success(`已将 ${row.capability_type} 写入运行时路由`);
  } catch (error) {
    message.error(`写入运行时路由失败: ${String(error)}`);
  } finally {
    runtimeApplyLoadingId.value = null;
  }
}

async function onPromoteAndApplyRuntimeRouting(row: OpsIntegrationVersion): Promise<void> {
  promoteRuntimeLoadingId.value = row.integration_id;
  try {
    if (row.status !== "active") {
      await rollbackOpsIntegration(row.integration_id, {
        tenant_id: tenantId.value,
        project_id: projectId.value,
      });
    }
    await applyOpsRuntimeRouting({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      integration_id: row.integration_id,
    });
    await Promise.all([reloadIntegrations(), reloadRuntimeStats()]);
    message.success(`已将 ${row.capability_type} 设为主版本并写入运行时路由`);
  } catch (error) {
    message.error(`设主并写路由失败: ${String(error)}`);
  } finally {
    promoteRuntimeLoadingId.value = null;
  }
}

async function onQuickRunIntegration(row: OpsIntegrationVersion): Promise<void> {
  quickRunLoadingId.value = row.integration_id;
  try {
    quickRunResult.value = await quickRunOpsIntegration({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      integration_id: row.integration_id,
      sample_input: {
        prompt: "生成一个简短测试样例",
        scene: "moonlit courtyard",
      },
      probe_connectivity: true,
    });
    await reloadRuntimeStats();
    quickRunModalVisible.value = true;
    message.success("快速试调用完成");
  } catch (error) {
    message.error(`快速试调用失败: ${String(error)}`);
  } finally {
    quickRunLoadingId.value = null;
  }
}

async function reloadCapabilities(): Promise<void> {
  try {
    const [standards, spec] = await Promise.all([
      getOpsCapabilityStandards(),
      getOpsAdapterSpec(),
    ]);
    capabilityRows.value = standards.items;
    adapterSpec.value = spec;
  } catch (error) {
    message.error(`加载能力标准失败: ${String(error)}`);
  }
}

async function reloadToken(): Promise<void> {
  tokenLoading.value = true;
  try {
    tokenInfo.value = await getOpsToken({
      tenant_id: tenantId.value,
      project_id: projectId.value,
    });
    if (!tokenVisible.value) {
      revealedToken.value = "";
    }
  } catch (error) {
    message.error(`加载 token 失败: ${String(error)}`);
  } finally {
    tokenLoading.value = false;
  }
}

async function reloadProviders(): Promise<void> {
  providerLoading.value = true;
  try {
    const [rowsResp, catalog] = await Promise.all([
      listOpsProviders({
        tenant_id: tenantId.value,
        project_id: projectId.value,
        capability_type: capabilityFilter.value || undefined,
        integration_status: statusFilter.value || undefined,
      }),
      listProviders(tenantId.value, projectId.value),
    ]);
    providerRows.value = rowsResp.items;
    providerCatalog.value = catalog;
    for (const row of rowsResp.items) {
      manualBindSelection[row.report_id] = row.matched_provider_id ?? null;
    }
  } catch (error) {
    message.error(`加载上报模型失败: ${String(error)}`);
  } finally {
    providerLoading.value = false;
  }
}

async function onToggleRevealToken(): Promise<void> {
  if (tokenVisible.value) {
    tokenVisible.value = false;
    return;
  }
  tokenLoading.value = true;
  try {
    const resp = await revealOpsToken({
      tenant_id: tenantId.value,
      project_id: projectId.value,
    });
    revealedToken.value = resp.token;
    tokenVisible.value = true;
  } catch (error) {
    message.error(`显示 token 失败: ${String(error)}`);
  } finally {
    tokenLoading.value = false;
  }
}

async function onCopyToken(): Promise<void> {
  try {
    if (!revealedToken.value) {
      const resp = await revealOpsToken({
        tenant_id: tenantId.value,
        project_id: projectId.value,
      });
      revealedToken.value = resp.token;
      tokenVisible.value = true;
    }
    if (!revealedToken.value) {
      throw new Error("token empty");
    }
    await navigator.clipboard.writeText(revealedToken.value);
    message.success("Token 已复制");
  } catch (error) {
    message.error(`复制失败: ${String(error)}`);
  }
}

async function onCopyText(value: string, label: string): Promise<void> {
  try {
    if (!value) {
      throw new Error(`${label} 为空`);
    }
    await navigator.clipboard.writeText(value);
    message.success(`${label} 已复制`);
  } catch (error) {
    message.error(`复制${label}失败: ${String(error)}`);
  }
}

async function onRegenerateToken(): Promise<void> {
  if (!window.confirm("重新生成后旧 token 会立即失效，是否继续？")) {
    return;
  }
  tokenLoading.value = true;
  try {
    const resp = await regenerateOpsToken({
      tenant_id: tenantId.value,
      project_id: projectId.value,
    });
    revealedToken.value = resp.token;
    tokenVisible.value = true;
    tokenInfo.value = await getOpsToken({
      tenant_id: tenantId.value,
      project_id: projectId.value,
    });
    message.success("Token 已重新生成");
  } catch (error) {
    message.error(`重新生成失败: ${String(error)}`);
  } finally {
    tokenLoading.value = false;
  }
}

function replaceProviderRow(next: OpsProviderRow): void {
  const index = providerRows.value.findIndex((item) => item.report_id === next.report_id);
  if (index >= 0) {
    providerRows.value[index] = next;
    manualBindSelection[next.report_id] = next.matched_provider_id ?? null;
  }
}

async function onAutoBind(row: OpsProviderRow): Promise<void> {
  try {
    const updated = await autoBindOpsProvider(row.report_id);
    replaceProviderRow(updated);
    message.success(`自动对接完成: ${row.provider_name} / 映射=${updated.mapping_status}`);
  } catch (error) {
    message.error(`自动对接失败: ${String(error)}`);
  }
}

async function onManualBind(row: OpsProviderRow): Promise<void> {
  try {
    const providerId = manualBindSelection[row.report_id] || null;
    const updated = await manualBindOpsProvider(row.report_id, {
      provider_id: providerId,
    });
    replaceProviderRow(updated);
    message.success("手动对接已保存");
  } catch (error) {
    message.error(`手动对接失败: ${String(error)}`);
  }
}

async function onTestProvider(row: OpsProviderRow): Promise<void> {
  try {
    const resp = await testOpsProvider(row.report_id);
    if (resp.ok) {
      message.success(`联通成功 (${resp.latency_ms ?? "-"}ms)`);
    } else {
      message.warning(`联通失败: ${resp.detail}`);
    }
    await reloadProviders();
  } catch (error) {
    message.error(`测试失败: ${String(error)}`);
  }
}

onMounted(() => {
  void reloadAll();
});
</script>

<style scoped>
.ops-page {
  padding: 8px 16px 18px;
}

.scope-card {
  margin-bottom: 12px;
}

.token-card :deep(.n-form-item-label) {
  min-width: 88px;
}

.storage-card :deep(.n-form-item-label) {
  min-width: 92px;
}

.ingress-value {
  margin-top: 2px;
  padding: 6px 8px;
  border-radius: 6px;
  background: #f5f6f7;
  color: #2b2f36;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
  font-size: 12px;
  word-break: break-all;
}

.spec-line {
  margin-bottom: 8px;
  white-space: normal;
  word-break: break-word;
  color: #444;
}

.mapping-detail {
  margin: 0;
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.5;
  color: #2b2f36;
}

.plan-panel {
  padding: 10px 12px;
  border-radius: 8px;
  background: #f7f8fa;
}

.plan-panel__title {
  margin-bottom: 6px;
  font-weight: 600;
  color: #1f2329;
}

.plan-panel__line {
  font-size: 12px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
  color: #4a5160;
}

.capability-stats-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px;
  margin-top: 12px;
}

.capability-stat-card {
  padding: 14px;
  border-radius: 12px;
  background: #f7f8fa;
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
  color: #1f2329;
}

.capability-stat-card__metrics {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.capability-stat-card__label {
  font-size: 12px;
  color: #7a8190;
  margin-bottom: 4px;
}

.capability-stat-card__value {
  font-size: 18px;
  font-weight: 700;
  color: #1f2329;
}

.capability-stat-card__meta {
  font-size: 12px;
  color: #4a5160;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.quickrun-stack {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.quickrun-summary-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
}

.quickrun-tile {
  padding: 10px 12px;
  border-radius: 10px;
  background: #f7f8fa;
}

.quickrun-tile__label {
  font-size: 12px;
  color: #7a8190;
  margin-bottom: 4px;
}

.quickrun-tile__value {
  font-size: 13px;
  font-weight: 600;
  color: #1f2329;
  word-break: break-word;
}

.quickrun-panel {
  padding: 10px 12px;
  border-radius: 10px;
  background: #f7f8fa;
}

.quickrun-panel__title {
  margin-bottom: 6px;
  font-size: 13px;
  font-weight: 600;
  color: #1f2329;
}

.quickrun-panel__line {
  font-size: 12px;
  line-height: 1.6;
  color: #4a5160;
  word-break: break-word;
}

.quickrun-empty {
  color: #7a8190;
}
</style>
