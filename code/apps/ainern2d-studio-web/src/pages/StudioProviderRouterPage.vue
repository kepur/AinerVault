<template>
  <div class="page-grid">
    <NCard title="SKILL 25 · Provider 接入中心">
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
        <NButton @click="onReloadAll">刷新全部</NButton>
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
        <NGridItem span="0:4 900:1"><NFormItem label="Text Gen"><NSwitch v-model:value="capTextGen" /></NFormItem></NGridItem>
        <NGridItem span="0:4 900:1"><NFormItem label="Embedding"><NSwitch v-model:value="capEmbedding" /></NFormItem></NGridItem>
        <NGridItem span="0:4 900:1"><NFormItem label="Multimodal"><NSwitch v-model:value="capMultimodal" /></NFormItem></NGridItem>
        <NGridItem span="0:4 900:1"><NFormItem label="Image Gen"><NSwitch v-model:value="capImageGen" /></NFormItem></NGridItem>
        <NGridItem span="0:4 900:1"><NFormItem label="Video Gen"><NSwitch v-model:value="capVideoGen" /></NFormItem></NGridItem>
        <NGridItem span="0:4 900:1"><NFormItem label="TTS"><NSwitch v-model:value="capTts" /></NFormItem></NGridItem>
        <NGridItem span="0:4 900:1"><NFormItem label="STT"><NSwitch v-model:value="capStt" /></NFormItem></NGridItem>
        <NGridItem span="0:4 900:1"><NFormItem label="Tool Calling"><NSwitch v-model:value="capToolCalling" /></NFormItem></NGridItem>
      </NGrid>
      <NFormItem label="Provider Probe Path">
        <NInput v-model:value="providerProbePath" placeholder="/models" />
      </NFormItem>
      <NSpace>
        <NButton type="primary" @click="onUpsertProvider">新增/更新 Provider</NButton>
        <NButton @click="onListProviders">刷新 Provider</NButton>
        <NButton type="info" @click="onBatchProbeProviders">批量探测</NButton>
      </NSpace>
      <NDataTable :columns="providerColumns" :data="filteredProviders" :pagination="{ pageSize: 8 }" />
      <NDataTable :columns="probeColumns" :data="providerProbeRows" :pagination="{ pageSize: 6 }" />
      <pre class="json-panel">{{ providerProbeText }}</pre>
    </NCard>

    <NCard title="Telegram 通知配置（SKILL 28）">
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 900:1"><NFormItem label="Enable"><NSwitch v-model:value="tgEnabled" /></NFormItem></NGridItem>
        <NGridItem span="0:2 900:1"><NFormItem label="Bot Token"><NInput v-model:value="tgBotToken" placeholder="123456:AA..." type="password" show-password-on="click" /></NFormItem></NGridItem>
        <NGridItem span="0:2 900:1"><NFormItem label="Chat ID"><NInput v-model:value="tgChatId" placeholder="-100xxxxxxxxxx" /></NFormItem></NGridItem>
        <NGridItem span="0:2 900:1"><NFormItem label="Thread ID (optional)"><NInput v-model:value="tgThreadId" placeholder="message_thread_id" /></NFormItem></NGridItem>
      </NGrid>
      <NFormItem label="Notify Events (comma separated)">
        <NInput v-model:value="tgNotifyEventsCsv" placeholder="run.failed,run.succeeded,job.failed,job.created,task.submitted,bootstrap.completed,plan.prompt.generated,rag.embedding.completed" />
      </NFormItem>
      <NSpace>
        <NButton type="primary" @click="onSaveTelegramSettings">保存 Telegram 配置</NButton>
        <NButton @click="onLoadTelegramSettings">加载 Telegram 配置</NButton>
        <NButton type="info" @click="onTestTelegramSettings">发送测试消息</NButton>
      </NSpace>
      <pre class="json-panel">{{ tgSettingsText }}</pre>
      <pre class="json-panel">{{ tgTestText }}</pre>
    </NCard>

    <NCard title="初始化默认配置（模型+角色可选 + WS 实时进度）">
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 900:1">
          <NFormItem label="默认 Model Profile（可选）">
            <NSelect
              v-model:value="bootstrapModelProfileId"
              :options="profileOptions"
              clearable
              filterable
              placeholder="不选则后端自动选第一个可用 profile"
            />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 900:1">
          <NFormItem label="初始化角色（可多选）">
            <NSelect
              v-model:value="bootstrapRoleIds"
              :options="bootstrapRoleOptions"
              multiple
              filterable
              clearable
              placeholder="默认初始化全部模板角色"
            />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 900:1">
          <NFormItem label="Enrich Rounds（langgraph-like）">
            <NInputNumber v-model:value="bootstrapEnrichRounds" :min="1" :max="6" style="width: 100%" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 900:1">
          <NFormItem label="Seed Mode">
            <NInput v-model:value="bootstrapSeedMode" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NGrid :cols="5" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:5 900:1"><NFormItem label="Roles"><NSwitch v-model:value="includeRoles" /></NFormItem></NGridItem>
        <NGridItem span="0:5 900:1"><NFormItem label="Skills"><NSwitch v-model:value="includeSkills" /></NFormItem></NGridItem>
        <NGridItem span="0:5 900:1"><NFormItem label="Routes"><NSwitch v-model:value="includeRoutes" /></NFormItem></NGridItem>
        <NGridItem span="0:5 900:1"><NFormItem label="Language"><NSwitch v-model:value="includeLanguages" /></NFormItem></NGridItem>
        <NGridItem span="0:5 900:1"><NFormItem label="Stage Routing"><NSwitch v-model:value="includeStageRouting" /></NFormItem></NGridItem>
      </NGrid>
      <NSpace>
        <NButton type="warning" @click="onBootstrapDefaults">开始初始化</NButton>
        <NTag :type="bootstrapWsConnected ? 'success' : 'warning'" :bordered="false">
          WS: {{ bootstrapWsConnected ? "connected" : "disconnected" }}
        </NTag>
        <NTag :bordered="false">session: {{ bootstrapSessionId || "-" }}</NTag>
      </NSpace>
      <pre class="json-panel">{{ bootstrapText }}</pre>
      <NCard size="small" title="WS 进度控制台">
        <pre class="json-panel ws-log">{{ bootstrapEventsText }}</pre>
      </NCard>
    </NCard>

    <NAlert v-if="message" type="success" :show-icon="true">{{ message }}</NAlert>
    <NAlert v-if="errorMessage" type="error" :show-icon="true">{{ errorMessage }}</NAlert>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onBeforeUnmount, onMounted, ref } from "vue";
import {
  NAlert,
  NButton,
  NCard,
  NDataTable,
  NFormItem,
  NGrid,
  NGridItem,
  NInput,
  NInputNumber,
  NSelect,
  NSpace,
  NSwitch,
  NTag,
  type DataTableColumns,
} from "naive-ui";

import {
  bootstrapDefaults,
  deleteProvider,
  getTelegramSettings,
  listModelProfiles,
  listProviders,
  testProviderConnection,
  testTelegramSettings,
  upsertProvider,
  upsertTelegramSettings,
  type ModelProfileResponse,
  type ProviderConnectionTestResponse,
  type ProviderResponse,
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
const providerProbePath = ref("/models");
const providerProbeText = ref("{}");
const providerProbeRows = ref<ProviderProbeRow[]>([]);

const profiles = ref<ModelProfileResponse[]>([]);

const tgEnabled = ref(false);
const tgBotToken = ref("");
const tgChatId = ref("");
const tgThreadId = ref("");
const tgNotifyEventsCsv = ref("run.failed,run.succeeded,job.failed,job.created,task.submitted,bootstrap.started,bootstrap.completed,bootstrap.failed,role.skill.run.completed,role.skill.run.failed,plan.prompt.generated,rag.embedding.completed");
const tgSettingsText = ref("{}");
const tgTestText = ref("{}");

const bootstrapSeedMode = ref("llm_template");
const bootstrapModelProfileId = ref<string | null>(null);
const bootstrapRoleIds = ref<string[]>([]);
const bootstrapEnrichRounds = ref<number | null>(2);
const includeRoles = ref(true);
const includeSkills = ref(true);
const includeRoutes = ref(true);
const includeLanguages = ref(true);
const includeStageRouting = ref(true);
const bootstrapSessionId = ref("");
const bootstrapWsConnected = ref(false);
const bootstrapEvents = ref<Array<Record<string, unknown>>>([]);
const bootstrapText = ref("{}");

const message = ref("");
const errorMessage = ref("");
let bootstrapWs: WebSocket | null = null;

interface ProviderProbeRow {
  provider_id: string;
  provider_name: string;
  connected: boolean;
  status_code: number | null;
  latency_ms: number | null;
  message: string;
  checked_at: string;
}

const bootstrapRoleOptions = [
  { label: "导演 director", value: "director" },
  { label: "场记 script_supervisor", value: "script_supervisor" },
  { label: "美术 art", value: "art" },
  { label: "灯光 lighting", value: "lighting" },
  { label: "武术 stunt", value: "stunt" },
  { label: "翻译 translator", value: "translator" },
];

const profileOptions = computed(() =>
  profiles.value.map((profile) => ({
    label: `${profile.purpose} · ${profile.name} (${profile.id})`,
    value: profile.id,
  }))
);

const filteredProviders = computed(() =>
  providers.value.filter((item) => {
    const keyword = providerKeyword.value.trim().toLowerCase();
    if (!keyword) {
      return true;
    }
    return item.name.toLowerCase().includes(keyword) || (item.endpoint || "").toLowerCase().includes(keyword);
  })
);

const bootstrapEventsText = computed(() =>
  JSON.stringify(bootstrapEvents.value, null, 2)
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
          h(
            NButton,
            {
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
            },
            { default: () => "Use" }
          ),
          h(
            NButton,
            {
              size: "small",
              type: "info",
              onClick: () => void onTestProvider(row.id),
            },
            { default: () => "Test" }
          ),
          h(
            NButton,
            {
              size: "small",
              type: "error",
              onClick: () => void onDeleteProvider(row.id),
            },
            { default: () => "Delete" }
          ),
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

function stringifyError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function clearNotice(): void {
  message.value = "";
  errorMessage.value = "";
}

function makeSessionId(): string {
  return `bootstrap_${Date.now()}_${Math.random().toString(16).slice(2, 10)}`;
}

function buildBootstrapWsUrl(sessionId: string): string {
  const rawBase = String(import.meta.env.VITE_API_BASE_URL || "").trim();
  try {
    const resolved = new URL(rawBase || "/", window.location.origin);
    const protocol = resolved.protocol === "https:" ? "wss:" : "ws:";
    return `${protocol}//${resolved.host}/api/v1/config/ws/bootstrap/${sessionId}`;
  } catch {
    const protocol = window.location.protocol === "https:" ? "wss" : "ws";
    return `${protocol}://${window.location.host}/api/v1/config/ws/bootstrap/${sessionId}`;
  }
}

function closeBootstrapWs(): void {
  if (bootstrapWs) {
    bootstrapWs.close();
    bootstrapWs = null;
  }
  bootstrapWsConnected.value = false;
}

function openBootstrapWs(sessionId: string): void {
  closeBootstrapWs();
  const url = buildBootstrapWsUrl(sessionId);
  bootstrapWs = new WebSocket(url);
  bootstrapWs.onopen = () => {
    bootstrapWsConnected.value = true;
  };
  bootstrapWs.onclose = () => {
    bootstrapWsConnected.value = false;
  };
  bootstrapWs.onerror = () => {
    bootstrapWsConnected.value = false;
  };
  bootstrapWs.onmessage = (event) => {
    try {
      const payload = JSON.parse(String(event.data || "{}")) as Record<string, unknown>;
      bootstrapEvents.value = [...bootstrapEvents.value, payload];
    } catch {
      bootstrapEvents.value = [...bootstrapEvents.value, { raw: String(event.data || "") }];
    }
  };
}

async function onListProviders(): Promise<void> {
  providers.value = await listProviders(tenantId.value, projectId.value);
}

async function onListProfiles(): Promise<void> {
  profiles.value = await listModelProfiles({
    tenant_id: tenantId.value,
    project_id: projectId.value,
  });
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
    message.value = `provider deleted: ${providerId}`;
  } catch (error) {
    errorMessage.value = `delete provider failed: ${stringifyError(error)}`;
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

async function onSaveTelegramSettings(): Promise<void> {
  clearNotice();
  try {
    const notifyEvents = tgNotifyEventsCsv.value
      .split(",")
      .map((item) => item.trim())
      .filter((item) => item.length > 0);
    const saved = await upsertTelegramSettings({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      enabled: tgEnabled.value,
      bot_token: tgBotToken.value || undefined,
      chat_id: tgChatId.value || undefined,
      thread_id: tgThreadId.value || undefined,
      parse_mode: "Markdown",
      notify_events: notifyEvents,
      schema_version: "1.0",
    });
    tgSettingsText.value = JSON.stringify(saved, null, 2);
    message.value = "telegram settings saved";
  } catch (error) {
    errorMessage.value = `save telegram settings failed: ${stringifyError(error)}`;
  }
}

async function onLoadTelegramSettings(): Promise<void> {
  clearNotice();
  try {
    const settings = await getTelegramSettings(tenantId.value, projectId.value);
    tgEnabled.value = settings.enabled;
    tgChatId.value = settings.chat_id || "";
    tgThreadId.value = settings.thread_id || "";
    tgNotifyEventsCsv.value = (settings.notify_events || []).join(",");
    tgBotToken.value = "";
    tgSettingsText.value = JSON.stringify(settings, null, 2);
    message.value = "telegram settings loaded";
  } catch (error) {
    errorMessage.value = `load telegram settings failed: ${stringifyError(error)}`;
  }
}

async function onTestTelegramSettings(): Promise<void> {
  clearNotice();
  try {
    const result = await testTelegramSettings({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      message_text: "[Ainer Studio] config test message",
      bot_token: tgBotToken.value || undefined,
      chat_id: tgChatId.value || undefined,
      thread_id: tgThreadId.value || undefined,
      parse_mode: "Markdown",
      timeout_ms: 5000,
    });
    tgTestText.value = JSON.stringify(result, null, 2);
    if (result.delivered) {
      message.value = "telegram test delivered";
      return;
    }
    errorMessage.value = `telegram test failed: ${result.message}`;
  } catch (error) {
    errorMessage.value = `test telegram settings failed: ${stringifyError(error)}`;
  }
}

async function onBootstrapDefaults(): Promise<void> {
  clearNotice();
  bootstrapEvents.value = [];
  bootstrapSessionId.value = makeSessionId();
  openBootstrapWs(bootstrapSessionId.value);
  try {
    const response = await bootstrapDefaults({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      seed_mode: bootstrapSeedMode.value,
      model_profile_id: bootstrapModelProfileId.value || undefined,
      role_ids: bootstrapRoleIds.value,
      enrich_rounds: bootstrapEnrichRounds.value || 2,
      session_id: bootstrapSessionId.value,
      include_roles: includeRoles.value,
      include_skills: includeSkills.value,
      include_routes: includeRoutes.value,
      include_language_settings: includeLanguages.value,
      include_stage_routing: includeStageRouting.value,
    });
    bootstrapText.value = JSON.stringify(response, null, 2);
    bootstrapEvents.value = [
      ...bootstrapEvents.value,
      { event: "bootstrap.response", payload: response },
    ];
    await onReloadAll();
    message.value = "bootstrap completed";
  } catch (error) {
    bootstrapEvents.value = [
      ...bootstrapEvents.value,
      { event: "bootstrap.error", error: stringifyError(error) },
    ];
    errorMessage.value = `bootstrap defaults failed: ${stringifyError(error)}`;
  }
}

async function onReloadAll(): Promise<void> {
  clearNotice();
  try {
    await Promise.all([onListProviders(), onListProfiles(), onLoadTelegramSettings()]);
    message.value = "数据已刷新";
  } catch (error) {
    errorMessage.value = `reload failed: ${stringifyError(error)}`;
  }
}

onMounted(() => {
  void onReloadAll();
});

onBeforeUnmount(() => {
  closeBootstrapWs();
});
</script>

<style scoped>
.ws-log {
  max-height: 280px;
  overflow: auto;
}
</style>
