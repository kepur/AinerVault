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
  autoBindOpsProvider,
  getOpsAdapterSpec,
  getOpsCapabilityStandards,
  getOpsToken,
  listOpsProviders,
  listProviders,
  manualBindOpsProvider,
  regenerateOpsToken,
  revealOpsToken,
  testOpsProvider,
  type AdapterSpecResponse,
  type CapabilityStandardItem,
  type OpsProviderRow,
  type OpsTokenResponse,
  type ProviderResponse,
} from "@/api/product";

const message = useMessage();

const tenantId = ref("default");
const projectId = ref("default");

const loading = ref(false);
const tokenLoading = ref(false);
const providerLoading = ref(false);

const tokenInfo = ref<OpsTokenResponse | null>(null);
const tokenVisible = ref(false);
const revealedToken = ref("");

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
  return Object.entries(adapterSpec.value.items).map(([capability, spec]) => ({
    capability,
    requestRequired: spec.request_required || [],
    responseRequired: spec.response_required || [],
    responseOptional: spec.response_optional || [],
  }));
});

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
      reloadCapabilities(),
      reloadProviders(),
    ]);
  } finally {
    loading.value = false;
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
</style>
