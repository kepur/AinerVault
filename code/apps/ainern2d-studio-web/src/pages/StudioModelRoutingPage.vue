<template>
  <div class="page-grid">
    <NCard title="SKILL 25 · Model Profile + Feature Route Map">
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
          <NSpace>
            <NButton @click="onReload">刷新基础数据</NButton>
            <NButton @click="onLoadRouting">加载路由</NButton>
            <NButton @click="onLoadHealth">健康概览</NButton>
          </NSpace>
        </NGridItem>
      </NGrid>
    </NCard>

    <NCard title="Model Profile 管理">
      <NGrid :cols="3" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Provider">
            <NSelect
              v-model:value="selectedProviderId"
              :options="providerOptions"
              filterable
              clearable
              placeholder="选择 Provider"
            />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Purpose">
            <NInput v-model:value="profilePurpose" placeholder="planner / embedding / critic / ..." />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Model Name">
            <NInput v-model:value="profileName" placeholder="gpt-4o-mini" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NFormItem label="Profile Params JSON">
        <NInput v-model:value="profileParamsJson" type="textarea" :autosize="{ minRows: 2, maxRows: 6 }" />
      </NFormItem>
      <NSpace>
        <NButton type="primary" @click="onUpsertProfile">保存 Profile</NButton>
        <NButton @click="onListProfiles">刷新 Profiles</NButton>
      </NSpace>
      <NDataTable :columns="profileColumns" :data="profiles" :pagination="{ pageSize: 8 }" />
    </NCard>

    <NCard title="Feature Route 映射（可视化 + JSON）">
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem v-for="item in featureBindingItems" :key="item.featureKey" span="0:2 900:1">
          <NFormItem :label="`Feature: ${item.featureKey}`">
            <NSelect
              :value="featureRouteBindings[item.featureKey]"
              :options="profileSelectOptions"
              placeholder="选择 Profile"
              clearable
              filterable
              @update:value="(value) => onUpdateFeatureBinding(item.featureKey, value)"
            />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NSpace>
        <NButton @click="onApplyVisualFeatureRoutes">应用可视化映射</NButton>
      </NSpace>
      <NFormItem label="Stage Routes JSON">
        <NInput v-model:value="stageRoutesJson" type="textarea" :autosize="{ minRows: 2, maxRows: 6 }" />
      </NFormItem>
      <NFormItem label="Fallback Chain JSON">
        <NInput v-model:value="fallbackJson" type="textarea" :autosize="{ minRows: 2, maxRows: 6 }" />
      </NFormItem>
      <NFormItem label="Feature Routes JSON（功能 -> Profile ID）">
        <NInput v-model:value="featureRoutesJson" type="textarea" :autosize="{ minRows: 2, maxRows: 6 }" />
      </NFormItem>
      <NSpace>
        <NButton type="primary" @click="onUpsertRouting">保存路由</NButton>
        <NButton @click="onLoadRouting">重新加载</NButton>
      </NSpace>
    </NCard>

    <NGrid :cols="2" :x-gap="12" :y-gap="12" responsive="screen" item-responsive>
      <NGridItem span="0:2 1200:1">
        <NCard title="Feature Matrix">
          <NSpace>
            <NButton @click="onLoadFeatureMatrix">刷新 Matrix</NButton>
          </NSpace>
          <pre class="json-panel">{{ featureMatrixText }}</pre>
        </NCard>
      </NGridItem>
      <NGridItem span="0:2 1200:1">
        <NCard title="配置健康状态">
          <pre class="json-panel">{{ configHealthText }}</pre>
        </NCard>
      </NGridItem>
    </NGrid>

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
  type DataTableColumns,
} from "naive-ui";

import {
  deleteModelProfile,
  getConfigHealth,
  getFeatureMatrix,
  getStageRouting,
  listModelProfiles,
  listProviders,
  upsertModelProfile,
  upsertStageRouting,
  type ModelProfileResponse,
  type ProviderResponse,
} from "@/api/product";

const tenantId = ref("default");
const projectId = ref("default");

const providers = ref<ProviderResponse[]>([]);
const profiles = ref<ModelProfileResponse[]>([]);
const selectedProviderId = ref("");
const profilePurpose = ref("planner");
const profileName = ref("gpt-4o-mini");
const profileParamsJson = ref('{"temperature":0.2}');

const stageRoutesJson = ref('{"skill_01":"planner","skill_10":"planner"}');
const fallbackJson = ref('{"planner":["fallback_a","fallback_b"]}');
const featureRoutesJson = ref("{}");
const featureRouteBindings = ref<Record<string, string>>({
  text_generation: "",
  embedding: "",
  multimodal: "",
  image_generation: "",
  video_generation: "",
  tts: "",
  stt: "",
});
const featureMatrixText = ref("{}");
const configHealthText = ref("{}");

const message = ref("");
const errorMessage = ref("");

interface FeatureBindingItem {
  featureKey: string;
}

const featureBindingItems = computed<FeatureBindingItem[]>(() => [
  { featureKey: "text_generation" },
  { featureKey: "embedding" },
  { featureKey: "multimodal" },
  { featureKey: "image_generation" },
  { featureKey: "video_generation" },
  { featureKey: "tts" },
  { featureKey: "stt" },
]);

const providerOptions = computed(() =>
  providers.value.map((item) => ({
    label: `${item.name} (${item.id})`,
    value: item.id,
  }))
);

const profileSelectOptions = computed(() =>
  profiles.value.map((profile) => ({
    label: `${profile.purpose} · ${profile.name} (${profile.id})`,
    value: profile.id,
  }))
);

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
          h(
            NButton,
            {
              size: "small",
              onClick: () => {
                selectedProviderId.value = row.provider_id;
                profilePurpose.value = row.purpose;
                profileName.value = row.name;
                profileParamsJson.value = JSON.stringify(row.params_json || {}, null, 2);
              },
            },
            { default: () => "Use" }
          ),
          h(
            NButton,
            {
              size: "small",
              type: "error",
              onClick: () => void onDeleteProfile(row.id),
            },
            { default: () => "Delete" }
          ),
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
  message.value = "feature route 映射已应用";
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

async function onUpsertProfile(): Promise<void> {
  clearNotice();
  if (!selectedProviderId.value) {
    errorMessage.value = "请选择 Provider";
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
    message.value = `profile upserted: ${profile.id}`;
  } catch (error) {
    errorMessage.value = `upsert profile failed: ${stringifyError(error)}`;
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
    message.value = "stage routing 已更新";
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

async function onReload(): Promise<void> {
  clearNotice();
  try {
    await onListProviders();
    await onListProfiles();
    await onLoadFeatureMatrix();
    await onLoadHealth();
    message.value = "基础数据已刷新";
  } catch (error) {
    errorMessage.value = `reload failed: ${stringifyError(error)}`;
  }
}

onMounted(() => {
  void onReload();
  void onLoadRouting();
});
</script>
