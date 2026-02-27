<template>
  <div class="page-grid">
    <NCard title="SKILL 25 · Provider / Router 配置">
      <NGrid :cols="3" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Tenant ID">
            <NInput v-model:value="tenantId" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Project ID">
            <NInput v-model:value="projectId" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Filter">
            <NInput v-model:value="providerKeyword" placeholder="provider keyword" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NSpace>
        <NButton type="primary" @click="onInitDefaults">初始化默认配置</NButton>
        <NButton @click="onListProviders">刷新 Provider</NButton>
      </NSpace>
    </NCard>

    <NCard title="Provider CRUD（公网/本地 + Token + 能力）">
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 900:1">
          <NFormItem label="Provider Name">
            <NInput v-model:value="providerName" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 900:1">
          <NFormItem label="Endpoint">
            <NInput v-model:value="providerEndpoint" placeholder="https://... or http://localhost:..." />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 900:1">
          <NFormItem label="Auth Mode">
            <NInput v-model:value="providerAuthMode" placeholder="api_key / bearer / none" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 900:1">
          <NFormItem label="Token / API Key">
            <NInput v-model:value="providerToken" type="password" show-password-on="click" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NFormItem label="Model Catalog (comma separated)">
        <NInput v-model:value="providerModelCatalogCsv" placeholder="gpt-4o-mini,text-embedding-3-large,..." />
      </NFormItem>
      <NGrid :cols="4" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:4 900:1">
          <NFormItem label="Text Gen"><NSwitch v-model:value="capTextGen" /></NFormItem>
        </NGridItem>
        <NGridItem span="0:4 900:1">
          <NFormItem label="Embedding"><NSwitch v-model:value="capEmbedding" /></NFormItem>
        </NGridItem>
        <NGridItem span="0:4 900:1">
          <NFormItem label="Multimodal"><NSwitch v-model:value="capMultimodal" /></NFormItem>
        </NGridItem>
        <NGridItem span="0:4 900:1">
          <NFormItem label="Image Gen"><NSwitch v-model:value="capImageGen" /></NFormItem>
        </NGridItem>
        <NGridItem span="0:4 900:1">
          <NFormItem label="Video Gen"><NSwitch v-model:value="capVideoGen" /></NFormItem>
        </NGridItem>
        <NGridItem span="0:4 900:1">
          <NFormItem label="TTS"><NSwitch v-model:value="capTts" /></NFormItem>
        </NGridItem>
        <NGridItem span="0:4 900:1">
          <NFormItem label="STT"><NSwitch v-model:value="capStt" /></NFormItem>
        </NGridItem>
        <NGridItem span="0:4 900:1">
          <NFormItem label="Tool Calling"><NSwitch v-model:value="capToolCalling" /></NFormItem>
        </NGridItem>
      </NGrid>
      <NSpace>
        <NButton type="primary" @click="onUpsertProvider">新增/更新 Provider</NButton>
        <NButton @click="onListProviders">刷新 Provider</NButton>
        <NButton type="info" @click="onBatchProbeProviders">批量健康探测</NButton>
      </NSpace>
      <NDataTable :columns="providerColumns" :data="filteredProviders" :pagination="{ pageSize: 8 }" />
      <NDataTable :columns="probeColumns" :data="providerProbeRows" :pagination="{ pageSize: 6 }" />
    </NCard>

    <NCard title="Model Profile + 功能路由映射">
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 900:1">
          <NFormItem label="Provider ID">
            <NInput v-model:value="selectedProviderId" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 900:1">
          <NFormItem label="Purpose">
            <NInput v-model:value="profilePurpose" placeholder="planner / embedding / critic / tts / ..." />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NFormItem label="Model Name">
        <NInput v-model:value="profileName" />
      </NFormItem>
      <NFormItem label="Profile Params JSON">
        <NInput v-model:value="profileParamsJson" type="textarea" :autosize="{ minRows: 2, maxRows: 5 }" />
      </NFormItem>
      <NSpace>
        <NButton type="primary" @click="onUpsertProfile">Upsert Profile</NButton>
        <NButton @click="onListProfiles">刷新 Profiles</NButton>
      </NSpace>
      <NDataTable :columns="profileColumns" :data="profiles" :pagination="{ pageSize: 8 }" />

      <NFormItem label="Stage Routes JSON">
        <NInput v-model:value="stageRoutesJson" type="textarea" :autosize="{ minRows: 2, maxRows: 5 }" />
      </NFormItem>
      <NFormItem label="Fallback Chain JSON">
        <NInput v-model:value="fallbackJson" type="textarea" :autosize="{ minRows: 2, maxRows: 5 }" />
      </NFormItem>
      <NFormItem label="Feature Routes JSON（功能->Profile）">
        <NInput v-model:value="featureRoutesJson" type="textarea" :autosize="{ minRows: 2, maxRows: 5 }" />
      </NFormItem>
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem v-for="item in featureBindingItems" :key="item.featureKey" span="0:2 900:1">
          <NFormItem :label="`Feature: ${item.featureKey}`">
            <NSelect
              :value="featureRouteBindings[item.featureKey]"
              :options="profileSelectOptions"
              placeholder="选择 Profile"
              filterable
              clearable
              @update:value="(value) => onUpdateFeatureBinding(item.featureKey, value)"
            />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NFormItem label="Provider Probe Path">
        <NInput v-model:value="providerProbePath" placeholder="/models" />
      </NFormItem>
      <NSpace>
        <NButton type="primary" @click="onApplyVisualFeatureRoutes">应用功能路由映射</NButton>
        <NButton type="warning" @click="onUpsertRouting">Upsert Routing</NButton>
        <NButton type="primary" @click="onTestProvider()">测试联通</NButton>
        <NButton @click="onLoadRouting">Load Routing</NButton>
        <NButton @click="onLoadHealth">Health</NButton>
        <NButton @click="onLoadFeatureMatrix">Feature Matrix</NButton>
      </NSpace>
      <pre class="json-panel">{{ providerProbeText }}</pre>
      <pre class="json-panel">{{ configHealthText }}</pre>
      <pre class="json-panel">{{ featureMatrixText }}</pre>
    </NCard>

    <NCard title="Telegram 通知配置（SKILL 28 通知入口）">
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 900:1">
          <NFormItem label="Enable">
            <NSwitch v-model:value="tgEnabled" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 900:1">
          <NFormItem label="Bot Token">
            <NInput v-model:value="tgBotToken" placeholder="123456:AA..." type="password" show-password-on="click" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 900:1">
          <NFormItem label="Chat ID">
            <NInput v-model:value="tgChatId" placeholder="-100xxxxxxxxxx" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 900:1">
          <NFormItem label="Thread ID (optional)">
            <NInput v-model:value="tgThreadId" placeholder="message_thread_id" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NFormItem label="Notify Events (comma separated)">
        <NInput v-model:value="tgNotifyEventsCsv" placeholder="run.failed,run.succeeded,job.failed" />
      </NFormItem>
      <NSpace>
        <NButton type="primary" @click="onSaveTelegramSettings">保存 Telegram 配置</NButton>
        <NButton @click="onLoadTelegramSettings">加载 Telegram 配置</NButton>
      </NSpace>
      <pre class="json-panel">{{ tgSettingsText }}</pre>
    </NCard>

    <NAlert v-if="message" type="success" :show-icon="true">{{ message }}</NAlert>
    <NAlert v-if="errorMessage" type="error" :show-icon="true">{{ errorMessage }}</NAlert>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref } from "vue";
import {
  NAlert,
  NButton,
  NCard,
  NDataTable,
  NFormItem,
  NGrid,
  NGridItem,
  NInput,
  NSelect,
  NSpace,
  NSwitch,
  type DataTableColumns,
} from "naive-ui";

import {
  type ModelProfileResponse,
  type ProviderConnectionTestResponse,
  type ProviderResponse,
  deleteModelProfile,
  deleteProvider,
  getConfigHealth,
  getFeatureMatrix,
  getStageRouting,
  getTelegramSettings,
  listModelProfiles,
  listProviders,
  testProviderConnection,
  upsertTelegramSettings,
  upsertModelProfile,
  upsertProvider,
  upsertStageRouting,
} from "@/api/product";

const tenantId = ref("default");
const projectId = ref("default");

const providerName = ref("openai");
const providerEndpoint = ref("https://api.openai.com/v1");
const providerAuthMode = ref("api_key");
const providerToken = ref("");
const providerModelCatalogCsv = ref("gpt-4o-mini,text-embedding-3-large");
const providerKeyword = ref("");
const providers = ref<ProviderResponse[]>([]);
const selectedProviderId = ref("");
const capTextGen = ref(true);
const capEmbedding = ref(true);
const capMultimodal = ref(false);
const capImageGen = ref(false);
const capVideoGen = ref(false);
const capTts = ref(false);
const capStt = ref(false);
const capToolCalling = ref(false);

const profilePurpose = ref("planner");
const profileName = ref("gpt-4o-mini");
const profileParamsJson = ref('{"temperature":0.2}');
const profiles = ref<ModelProfileResponse[]>([]);
const stageRoutesJson = ref('{"skill_01":"planner","skill_10":"planner"}');
const fallbackJson = ref('{"planner":["fallback_a","fallback_b"]}');
const featureRoutesJson = ref('{"embedding":"embedding","text_generation":"planner"}');
const featureRouteBindings = ref<Record<string, string>>({
  text_generation: "",
  embedding: "",
  multimodal: "",
  image_generation: "",
  video_generation: "",
  tts: "",
  stt: "",
});
const providerProbePath = ref("/models");
const providerProbeText = ref("{}");
const providerProbeRows = ref<ProviderProbeRow[]>([]);
const configHealthText = ref("{}");
const featureMatrixText = ref("{}");

const tgEnabled = ref(false);
const tgBotToken = ref("");
const tgChatId = ref("");
const tgThreadId = ref("");
const tgNotifyEventsCsv = ref("run.failed,run.succeeded,job.failed");
const tgSettingsText = ref("{}");

const message = ref("");
const errorMessage = ref("");

interface ProviderProbeRow {
  provider_id: string;
  provider_name: string;
  connected: boolean;
  status_code: number | null;
  latency_ms: number | null;
  message: string;
  checked_at: string;
}

interface FeatureBindingItem {
  featureKey: string;
}

const filteredProviders = computed(() =>
  providers.value.filter((item) => {
    const keyword = providerKeyword.value.trim().toLowerCase();
    if (!keyword) {
      return true;
    }
    return item.name.toLowerCase().includes(keyword) || (item.endpoint || "").toLowerCase().includes(keyword);
  })
);

const featureBindingItems = computed<FeatureBindingItem[]>(() => [
  { featureKey: "text_generation" },
  { featureKey: "embedding" },
  { featureKey: "multimodal" },
  { featureKey: "image_generation" },
  { featureKey: "video_generation" },
  { featureKey: "tts" },
  { featureKey: "stt" },
]);

const profileSelectOptions = computed(() =>
  profiles.value.map((profile) => ({
    label: `${profile.purpose} · ${profile.name} (${profile.id})`,
    value: profile.id,
  }))
);

const providerColumns: DataTableColumns<ProviderResponse> = [
  { title: "ID", key: "id" },
  { title: "Name", key: "name" },
  { title: "Endpoint", key: "endpoint" },
  { title: "Auth", key: "auth_mode" },
  { title: "Token", key: "access_token_masked" },
  {
    title: "Caps",
    key: "capability_flags",
    render: (row) => {
      const caps = row.capability_flags || {};
      const tags: string[] = [];
      if (caps.supports_text_generation) tags.push("text");
      if (caps.supports_embedding) tags.push("embedding");
      if (caps.supports_multimodal) tags.push("multimodal");
      if (caps.supports_image_generation) tags.push("image");
      if (caps.supports_video_generation) tags.push("video");
      if (caps.supports_tts) tags.push("tts");
      return tags.join(",");
    },
  },
  {
    title: "Action",
    key: "action",
    render: (row) =>
      h(NSpace, { size: 6 }, {
        default: () => [
          h(NButton, {
            size: "small",
            onClick: () => {
              selectedProviderId.value = row.id;
              providerName.value = row.name;
              providerEndpoint.value = row.endpoint || "";
              providerAuthMode.value = row.auth_mode || "api_key";
              providerToken.value = "";
              providerModelCatalogCsv.value = (row.model_catalog || []).join(",");
              const caps = row.capability_flags || {};
              capTextGen.value = Boolean(caps.supports_text_generation);
              capEmbedding.value = Boolean(caps.supports_embedding);
              capMultimodal.value = Boolean(caps.supports_multimodal);
              capImageGen.value = Boolean(caps.supports_image_generation);
              capVideoGen.value = Boolean(caps.supports_video_generation);
              capTts.value = Boolean(caps.supports_tts);
              capStt.value = Boolean(caps.supports_stt);
              capToolCalling.value = Boolean(caps.supports_tool_calling);
            },
          }, { default: () => "Use" }),
          h(NButton, {
            size: "small",
            type: "info",
            onClick: () => void onTestProvider(row.id),
          }, { default: () => "Test" }),
          h(NButton, {
            size: "small",
            type: "error",
            onClick: () => void onDeleteProvider(row.id),
          }, { default: () => "Delete" }),
        ],
      }),
  },
];

const probeColumns: DataTableColumns<ProviderProbeRow> = [
  { title: "Provider", key: "provider_name" },
  { title: "Connected", key: "connected", render: (row) => (row.connected ? "yes" : "no") },
  { title: "Status", key: "status_code", render: (row) => String(row.status_code ?? "-") },
  { title: "Latency(ms)", key: "latency_ms", render: (row) => String(row.latency_ms ?? "-") },
  { title: "Message", key: "message" },
  { title: "Checked At", key: "checked_at" },
];

const profileColumns: DataTableColumns<ModelProfileResponse> = [
  { title: "ID", key: "id" },
  { title: "Provider", key: "provider_id" },
  { title: "Purpose", key: "purpose" },
  { title: "Model", key: "name" },
  {
    title: "Action",
    key: "action",
    render: (row) =>
      h(NSpace, { size: 6 }, {
        default: () => [
          h(NButton, {
            size: "small",
            type: "info",
            onClick: () => {
              selectedProviderId.value = row.provider_id;
              profilePurpose.value = row.purpose;
              profileName.value = row.name;
              profileParamsJson.value = JSON.stringify(row.params_json || {}, null, 2);
            },
          }, { default: () => "Use" }),
          h(NButton, {
            size: "small",
            type: "error",
            onClick: () => void onDeleteProfile(row.id),
          }, { default: () => "Delete" }),
        ],
      }),
  },
];

function stringifyError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function clearNotice(): void {
  message.value = "";
  errorMessage.value = "";
}

function parseJsonObject(text: string): Record<string, unknown> {
  const parsed = JSON.parse(text) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("json must be object");
  }
  return parsed as Record<string, unknown>;
}

function syncFeatureBindingsFromJson(): void {
  const source = parseJsonObject(featureRoutesJson.value);
  const next = { ...featureRouteBindings.value };
  for (const item of featureBindingItems.value) {
    const raw = source[item.featureKey];
    next[item.featureKey] = typeof raw === "string" ? raw : "";
  }
  featureRouteBindings.value = next;
}

function syncFeatureJsonFromBindings(): void {
  const payload: Record<string, unknown> = {};
  for (const item of featureBindingItems.value) {
    const value = (featureRouteBindings.value[item.featureKey] || "").trim();
    if (value) {
      payload[item.featureKey] = value;
    }
  }
  featureRoutesJson.value = JSON.stringify(payload, null, 2);
}

function onUpdateFeatureBinding(featureKey: string, value: string | null): void {
  featureRouteBindings.value = {
    ...featureRouteBindings.value,
    [featureKey]: value || "",
  };
}

function profileSupportsFeature(profileId: string, featureKey: string): boolean {
  const profile = profiles.value.find((item) => item.id === profileId);
  if (!profile) {
    return false;
  }
  const provider = providers.value.find((item) => item.id === profile.provider_id);
  if (!provider) {
    return false;
  }
  const caps = provider.capability_flags || {};
  const featureGateMap: Record<string, boolean> = {
    text_generation: Boolean(caps.supports_text_generation),
    embedding: Boolean(caps.supports_embedding),
    multimodal: Boolean(caps.supports_multimodal),
    image_generation: Boolean(caps.supports_image_generation),
    video_generation: Boolean(caps.supports_video_generation),
    tts: Boolean(caps.supports_tts),
    stt: Boolean(caps.supports_stt),
  };
  return featureGateMap[featureKey] ?? false;
}

async function onListProviders(): Promise<void> {
  clearNotice();
  try {
    providers.value = await listProviders(tenantId.value, projectId.value);
  } catch (error) {
    errorMessage.value = `list providers failed: ${stringifyError(error)}`;
  }
}

async function onUpsertProvider(): Promise<void> {
  clearNotice();
  try {
    const catalog = providerModelCatalogCsv.value
      .split(",")
      .map((item) => item.trim())
      .filter((item) => item.length > 0);
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
    selectedProviderId.value = provider.id;
    await onListProviders();
    await onLoadFeatureMatrix();
    message.value = `provider upserted: ${provider.id}`;
  } catch (error) {
    errorMessage.value = `upsert provider failed: ${stringifyError(error)}`;
  }
}

async function onDeleteProvider(providerId: string): Promise<void> {
  clearNotice();
  try {
    await deleteProvider(providerId, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
    });
    if (selectedProviderId.value === providerId) {
      selectedProviderId.value = "";
    }
    await onListProviders();
    await onListProfiles();
    await onLoadFeatureMatrix();
    message.value = `provider deleted: ${providerId}`;
  } catch (error) {
    errorMessage.value = `delete provider failed: ${stringifyError(error)}`;
  }
}

async function onUpsertProfile(): Promise<void> {
  clearNotice();
  if (!selectedProviderId.value) {
    errorMessage.value = "select provider first";
    return;
  }
  try {
    const profile = await upsertModelProfile({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      provider_id: selectedProviderId.value,
      purpose: profilePurpose.value,
      name: profileName.value,
      params_json: parseJsonObject(profileParamsJson.value),
    });
    await onListProfiles();
    await onLoadFeatureMatrix();
    message.value = `profile upserted: ${profile.id}`;
  } catch (error) {
    errorMessage.value = `upsert profile failed: ${stringifyError(error)}`;
  }
}

async function onListProfiles(): Promise<void> {
  clearNotice();
  try {
    profiles.value = await listModelProfiles({
      tenant_id: tenantId.value,
      project_id: projectId.value,
    });
    try {
      syncFeatureBindingsFromJson();
    } catch {
      // Keep manual JSON as-is when parse fails; user can fix json text then re-apply.
    }
  } catch (error) {
    errorMessage.value = `list profiles failed: ${stringifyError(error)}`;
  }
}

async function onDeleteProfile(profileId: string): Promise<void> {
  clearNotice();
  try {
    await deleteModelProfile(profileId, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
    });
    await onListProfiles();
    await onLoadFeatureMatrix();
    message.value = `profile deleted: ${profileId}`;
  } catch (error) {
    errorMessage.value = `delete profile failed: ${stringifyError(error)}`;
  }
}

async function onUpsertRouting(): Promise<void> {
  clearNotice();
  try {
    syncFeatureJsonFromBindings();
    await upsertStageRouting({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      routes: parseJsonObject(stageRoutesJson.value),
      fallback_chain: parseJsonObject(fallbackJson.value),
      feature_routes: parseJsonObject(featureRoutesJson.value),
    });
    message.value = "stage routing updated";
  } catch (error) {
    errorMessage.value = `upsert routing failed: ${stringifyError(error)}`;
  }
}

async function onLoadRouting(): Promise<void> {
  clearNotice();
  try {
    const routing = await getStageRouting(tenantId.value, projectId.value);
    stageRoutesJson.value = JSON.stringify(routing.routes || {}, null, 2);
    fallbackJson.value = JSON.stringify(routing.fallback_chain || {}, null, 2);
    featureRoutesJson.value = JSON.stringify(routing.feature_routes || {}, null, 2);
    syncFeatureBindingsFromJson();
    message.value = "routing loaded";
  } catch (error) {
    errorMessage.value = `load routing failed: ${stringifyError(error)}`;
  }
}

function onApplyVisualFeatureRoutes(): void {
  clearNotice();
  for (const item of featureBindingItems.value) {
    const profileId = (featureRouteBindings.value[item.featureKey] || "").trim();
    if (!profileId) {
      continue;
    }
    if (!profileSupportsFeature(profileId, item.featureKey)) {
      errorMessage.value = `feature ${item.featureKey} incompatible with profile ${profileId}`;
      return;
    }
  }
  syncFeatureJsonFromBindings();
  message.value = "feature routes mapped from visual bindings";
}

async function onTestProvider(providerId?: string): Promise<void> {
  clearNotice();
  const targetProviderId = (providerId || selectedProviderId.value).trim();
  if (!targetProviderId) {
    errorMessage.value = "select provider first";
    return;
  }
  try {
    const response = await testProviderConnection(targetProviderId, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      probe_path: providerProbePath.value || "/models",
      timeout_ms: 5000,
    });
    upsertProbeRow(toProbeRow(response));
    providerProbeText.value = JSON.stringify(response, null, 2);
    selectedProviderId.value = targetProviderId;
    if (response.connected) {
      message.value = `provider connected: ${response.provider_name} (${response.status_code ?? "ok"})`;
      return;
    }
    errorMessage.value = `provider not connected: ${response.message}`;
  } catch (error) {
    errorMessage.value = `test provider failed: ${stringifyError(error)}`;
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

function upsertProbeRow(row: ProviderProbeRow): void {
  const index = providerProbeRows.value.findIndex((item) => item.provider_id === row.provider_id);
  if (index >= 0) {
    providerProbeRows.value.splice(index, 1, row);
    return;
  }
  providerProbeRows.value = [row, ...providerProbeRows.value];
}

async function onBatchProbeProviders(): Promise<void> {
  clearNotice();
  if (providers.value.length === 0) {
    errorMessage.value = "no providers to probe";
    return;
  }
  const rows: ProviderProbeRow[] = [];
  for (const provider of providers.value) {
    try {
      const response = await testProviderConnection(provider.id, {
        tenant_id: tenantId.value,
        project_id: projectId.value,
        probe_path: providerProbePath.value || "/models",
        timeout_ms: 5000,
      });
      rows.push(toProbeRow(response));
    } catch (error) {
      rows.push({
        provider_id: provider.id,
        provider_name: provider.name,
        connected: false,
        status_code: null,
        latency_ms: null,
        message: `probe_failed:${stringifyError(error)}`,
        checked_at: new Date().toISOString(),
      });
    }
  }
  providerProbeRows.value = rows;
  message.value = `batch probe done: ${rows.length} providers`;
}

async function onLoadFeatureMatrix(): Promise<void> {
  clearNotice();
  try {
    const matrix = await getFeatureMatrix(tenantId.value, projectId.value);
    featureMatrixText.value = JSON.stringify(matrix, null, 2);
  } catch (error) {
    errorMessage.value = `load feature matrix failed: ${stringifyError(error)}`;
  }
}

async function onLoadHealth(): Promise<void> {
  clearNotice();
  try {
    const health = await getConfigHealth(tenantId.value, projectId.value);
    configHealthText.value = JSON.stringify(health, null, 2);
  } catch (error) {
    errorMessage.value = `load health failed: ${stringifyError(error)}`;
  }
}

async function onInitDefaults(): Promise<void> {
  clearNotice();
  try {
    await onUpsertProvider();
    await onUpsertProfile();
    await onUpsertRouting();
    await onLoadHealth();
    await onListProfiles();
    await onLoadFeatureMatrix();
    message.value = "default provider/router initialized";
  } catch (error) {
    errorMessage.value = `init defaults failed: ${stringifyError(error)}`;
  }
}

async function onSaveTelegramSettings(): Promise<void> {
  clearNotice();
  try {
    const events = tgNotifyEventsCsv.value
      .split(",")
      .map((item) => item.trim())
      .filter((item) => item.length > 0);
    const response = await upsertTelegramSettings({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      enabled: tgEnabled.value,
      bot_token: tgBotToken.value || undefined,
      chat_id: tgChatId.value || undefined,
      thread_id: tgThreadId.value || undefined,
      parse_mode: "Markdown",
      notify_events: events,
      schema_version: "1.0",
    });
    tgSettingsText.value = JSON.stringify(response, null, 2);
    message.value = "telegram settings saved";
  } catch (error) {
    errorMessage.value = `save telegram settings failed: ${stringifyError(error)}`;
  }
}

async function onLoadTelegramSettings(): Promise<void> {
  clearNotice();
  try {
    const response = await getTelegramSettings(tenantId.value, projectId.value);
    tgEnabled.value = response.enabled;
    tgChatId.value = response.chat_id || "";
    tgThreadId.value = response.thread_id || "";
    tgNotifyEventsCsv.value = (response.notify_events || []).join(",");
    tgSettingsText.value = JSON.stringify(response, null, 2);
  } catch (error) {
    errorMessage.value = `load telegram settings failed: ${stringifyError(error)}`;
  }
}

onMounted(() => {
  void onListProviders();
  void onListProfiles();
  void onLoadRouting();
  void onLoadHealth();
  void onLoadFeatureMatrix();
  void onLoadTelegramSettings();
});
</script>
