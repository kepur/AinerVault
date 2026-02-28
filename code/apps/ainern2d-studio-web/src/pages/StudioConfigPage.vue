<template>
  <div class="page-grid">
    <NCard title="SKILL 25 + 26 + 27 · Config / RAG / Culture">
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Tenant ID">
            <NInput v-model:value="tenantId" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Project ID">
            <NInput v-model:value="projectId" />
          </NFormItem>
        </NGridItem>
      </NGrid>
    </NCard>

    <NCard title="Config Center（SKILL 25）">
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Provider Name">
            <NInput v-model:value="providerName" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Provider Endpoint">
            <NInput v-model:value="providerEndpoint" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NSpace>
        <NButton type="primary" @click="onUpsertProvider">Upsert Provider</NButton>
        <NButton @click="onListProviders">Reload Providers</NButton>
      </NSpace>
      <NDataTable :columns="providerColumns" :data="providers" :pagination="{ pageSize: 6 }" />

      <NDivider />

      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Selected Provider ID">
            <NInput v-model:value="selectedProviderId" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Profile Purpose">
            <NInput v-model:value="profilePurpose" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Profile Name">
            <NInput v-model:value="profileName" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NFormItem label="Profile Params JSON">
        <NInput v-model:value="profileParamsJson" type="textarea" :autosize="{ minRows: 2, maxRows: 5 }" />
      </NFormItem>
      <NFormItem label="Stage Routes JSON">
        <NInput v-model:value="stageRoutesJson" type="textarea" :autosize="{ minRows: 2, maxRows: 5 }" />
      </NFormItem>
      <NFormItem label="Fallback Chain JSON">
        <NInput v-model:value="fallbackJson" type="textarea" :autosize="{ minRows: 2, maxRows: 5 }" />
      </NFormItem>
      <NSpace>
        <NButton type="primary" @click="onUpsertProfile">Upsert Profile</NButton>
        <NButton type="warning" @click="onUpsertRouting">Upsert Stage Routing</NButton>
        <NButton type="info" @click="onLoadHealth">Health Check</NButton>
      </NSpace>
      <pre class="json-panel">{{ configHealthText }}</pre>
    </NCard>

    <NCard title="Language Settings（中英+小语种）">
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 640:1">
          <NFormItem label="默认输入语言">
            <NInput v-model:value="languageSource" placeholder="zh-CN" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 640:1">
          <NFormItem label="默认输出语言列表（逗号分隔）">
            <NInput v-model:value="languageTargetsCsv" placeholder="en-US,ja-JP,ar-SA" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NFormItem label="启用语言定义 JSON（含小语种/RTL）">
        <NInput v-model:value="languageDefinitionsJson" type="textarea" :autosize="{ minRows: 6, maxRows: 12 }" />
      </NFormItem>
      <NFormItem label="翻译备注">
        <NInput v-model:value="languageNotes" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" />
      </NFormItem>
      <NFormItem label="术语表 JSON">
        <NInput v-model:value="languageGlossaryJson" type="textarea" :autosize="{ minRows: 2, maxRows: 6 }" />
      </NFormItem>
      <NSpace>
        <NButton type="primary" @click="onUpsertLanguageSettings">保存语言配置</NButton>
        <NButton @click="onLoadLanguageSettings">加载语言配置</NButton>
      </NSpace>
      <pre class="json-panel">{{ languageSettingsText }}</pre>
    </NCard>

    <NCard title="RAG + Persona Console（SKILL 26）">
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Collection Name">
            <NInput v-model:value="collectionName" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 640:1">
          <NFormItem label="KB Version Name">
            <NInput v-model:value="kbVersionName" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NSpace>
        <NButton type="primary" @click="onCreateCollection">Create Collection</NButton>
        <NButton @click="onCreateKbVersion">Create KB Version</NButton>
      </NSpace>

      <NDivider />

      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Persona Pack Name">
            <NInput v-model:value="personaPackName" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Persona Version Name">
            <NInput v-model:value="personaVersionName" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NSpace>
        <NButton type="primary" @click="onCreatePersonaPack">Create Persona Pack</NButton>
        <NButton @click="onCreatePersonaVersion">Create Persona Version</NButton>
        <NButton type="warning" @click="onBindPersona">Bind Persona Resources</NButton>
      </NSpace>

      <NFormItem label="Persona Preview Query">
        <NInput v-model:value="personaQuery" />
      </NFormItem>
      <NButton type="info" @click="onPreviewPersona">Preview Persona</NButton>
      <pre class="json-panel">{{ personaPreviewText }}</pre>
    </NCard>

    <NCard title="Culture Pack Manager（SKILL 27）">
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Culture Pack ID">
            <NInput v-model:value="culturePackId" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Display Name">
            <NInput v-model:value="cultureDisplayName" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NFormItem label="Constraints JSON">
        <NInput v-model:value="cultureConstraintsJson" type="textarea" :autosize="{ minRows: 3, maxRows: 6 }" />
      </NFormItem>
      <NSpace>
        <NButton type="primary" @click="onCreateCulturePack">Create Culture Pack</NButton>
        <NButton type="info" @click="onExportCulturePack">Export Constraints</NButton>
      </NSpace>
      <pre class="json-panel">{{ cultureExportText }}</pre>
    </NCard>

    <NAlert v-if="message" type="success" :show-icon="true">{{ message }}</NAlert>
    <NAlert v-if="errorMessage" type="error" :show-icon="true">{{ errorMessage }}</NAlert>
  </div>
</template>

<script setup lang="ts">
import { h, onMounted, ref } from "vue";
import {
  NAlert,
  NButton,
  NCard,
  NDataTable,
  NDivider,
  NFormItem,
  NGrid,
  NGridItem,
  NInput,
  NSpace,
  type DataTableColumns,
} from "naive-ui";
import { useI18n } from "@/composables/useI18n";


import {
  type LanguageDefinition,
  type ProviderResponse,
  bindPersonaResources,
  createCulturePack,
  createKbVersion,
  createPersonaPack,
  createPersonaVersion,
  createRagCollection,
  exportCulturePack,
  getConfigHealth,
  getLanguageSettings,
  listProviders,
  previewPersona,
  upsertLanguageSettings,
  upsertModelProfile,
  upsertProvider,
  upsertStageRouting,
} from "@/api/product";

const { t } = useI18n();

const tenantId = ref("default");
const projectId = ref("default");

const providerName = ref("openai");
const providerEndpoint = ref("https://api.openai.com/v1");
const selectedProviderId = ref("");
const profilePurpose = ref("planner");
const profileName = ref("gpt-4o-mini");
const profileParamsJson = ref('{"temperature":0.2}');
const stageRoutesJson = ref('{"skill_01":"planner","skill_10":"planner"}');
const fallbackJson = ref('{"planner":["fallback_a","fallback_b"]}');

const providers = ref<ProviderResponse[]>([]);
const configHealthText = ref("{}");

const languageSource = ref("zh-CN");
const languageTargetsCsv = ref("en-US,ja-JP");
const languageDefinitionsJson = ref(
  JSON.stringify(
    [
      { language_code: "zh-CN", label: "简体中文", locales: ["zh-CN"], direction: "ltr", enabled: true },
      { language_code: "en-US", label: "English", locales: ["en-US", "en-GB"], direction: "ltr", enabled: true },
      { language_code: "ja-JP", label: "日本語", locales: ["ja-JP"], direction: "ltr", enabled: true },
      { language_code: "ar-SA", label: "العربية", locales: ["ar-SA"], direction: "rtl", enabled: true },
    ],
    null,
    2
  )
);
const languageNotes = ref("支持中英与小语种输出");
const languageGlossaryJson = ref('{"wuxia":{"en-US":"martial heroes"}}');
const languageSettingsText = ref("{}");

const collectionName = ref("kb_main");
const kbVersionName = ref("v1");
const createdCollectionId = ref("");
const createdKbVersionId = ref("");

const personaPackName = ref("director_A");
const personaVersionName = ref("v1");
const createdPersonaPackId = ref("");
const createdPersonaVersionId = ref("");
const personaQuery = ref("sword tavern duel");
const personaPreviewText = ref("{}");

const culturePackId = ref("cn_wuxia");
const cultureDisplayName = ref("中式武侠");
const cultureConstraintsJson = ref('{"visual_do":["ink"],"visual_dont":["neon"]}');
const cultureExportText = ref("{}");

const message = ref("");
const errorMessage = ref("");

const providerColumns: DataTableColumns<ProviderResponse> = [
  { title: "ID", key: "id" },
  { title: "Name", key: "name" },
  { title: "Endpoint", key: "endpoint" },
  {
    title: "Action",
    key: "action",
    render: (row) =>
      h(
        NButton,
        {
          size: "small",
          onClick: () => {
            selectedProviderId.value = row.id;
          },
        },
        { default: () => "Use" }
      ),
  },
];

function stringifyError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

function toPrettyJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function parseJsonObject(text: string): Record<string, unknown> {
  const value = JSON.parse(text) as unknown;
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("json must be object");
  }
  return value as Record<string, unknown>;
}

function parseJsonArray<T>(text: string): T[] {
  const value = JSON.parse(text) as unknown;
  if (!Array.isArray(value)) {
    throw new Error("json must be array");
  }
  return value as T[];
}

function clearNotice(): void {
  message.value = "";
  errorMessage.value = "";
}

function parseLanguageTargets(csvText: string): string[] {
  return csvText
    .split(",")
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

async function onUpsertProvider(): Promise<void> {
  clearNotice();
  try {
    const provider = await upsertProvider({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      name: providerName.value,
      endpoint: providerEndpoint.value,
      auth_mode: "api_key",
    });
    selectedProviderId.value = provider.id;
    await onListProviders();
    message.value = `provider upserted: ${provider.id}`;
  } catch (error) {
    errorMessage.value = `upsert provider failed: ${stringifyError(error)}`;
  }
}

async function onListProviders(): Promise<void> {
  clearNotice();
  try {
    providers.value = await listProviders(tenantId.value, projectId.value);
    if (!selectedProviderId.value && providers.value.length > 0) {
      selectedProviderId.value = providers.value[0].id;
    }
  } catch (error) {
    errorMessage.value = `list providers failed: ${stringifyError(error)}`;
  }
}

async function onUpsertProfile(): Promise<void> {
  clearNotice();
  try {
    const params = parseJsonObject(profileParamsJson.value);
    await upsertModelProfile({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      provider_id: selectedProviderId.value,
      purpose: profilePurpose.value,
      name: profileName.value,
      params_json: params,
    });
    message.value = "profile upserted";
  } catch (error) {
    errorMessage.value = `upsert profile failed: ${stringifyError(error)}`;
  }
}

async function onUpsertRouting(): Promise<void> {
  clearNotice();
  try {
    await upsertStageRouting({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      routes: parseJsonObject(stageRoutesJson.value),
      fallback_chain: parseJsonObject(fallbackJson.value),
    });
    message.value = "stage routing upserted";
  } catch (error) {
    errorMessage.value = `upsert stage routing failed: ${stringifyError(error)}`;
  }
}

async function onLoadHealth(): Promise<void> {
  clearNotice();
  try {
    const health = await getConfigHealth(tenantId.value, projectId.value);
    configHealthText.value = toPrettyJson(health);
  } catch (error) {
    errorMessage.value = `load health failed: ${stringifyError(error)}`;
  }
}

async function onUpsertLanguageSettings(): Promise<void> {
  clearNotice();
  try {
    const enabledLanguages = parseJsonArray<LanguageDefinition>(languageDefinitionsJson.value);
    const glossary = parseJsonObject(languageGlossaryJson.value);
    const response = await upsertLanguageSettings({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      default_source_language: languageSource.value,
      default_target_languages: parseLanguageTargets(languageTargetsCsv.value),
      enabled_languages: enabledLanguages,
      translation_notes: languageNotes.value,
      glossary,
      schema_version: "1.0",
    });
    languageSettingsText.value = toPrettyJson(response);
    message.value = "language settings saved";
  } catch (error) {
    errorMessage.value = `save language settings failed: ${stringifyError(error)}`;
  }
}

async function onLoadLanguageSettings(): Promise<void> {
  clearNotice();
  try {
    const settings = await getLanguageSettings(tenantId.value, projectId.value);
    languageSource.value = settings.default_source_language;
    languageTargetsCsv.value = settings.default_target_languages.join(",");
    languageDefinitionsJson.value = toPrettyJson(settings.enabled_languages);
    languageNotes.value = settings.translation_notes || "";
    languageGlossaryJson.value = toPrettyJson(settings.glossary || {});
    languageSettingsText.value = toPrettyJson(settings);
  } catch (error) {
    errorMessage.value = `load language settings failed: ${stringifyError(error)}`;
  }
}

async function onCreateCollection(): Promise<void> {
  clearNotice();
  try {
    const collection = await createRagCollection({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      name: collectionName.value,
      language_code: "zh",
    });
    createdCollectionId.value = collection.id;
    message.value = `collection created: ${collection.id}`;
  } catch (error) {
    errorMessage.value = `create collection failed: ${stringifyError(error)}`;
  }
}

async function onCreateKbVersion(): Promise<void> {
  clearNotice();
  if (!createdCollectionId.value) {
    errorMessage.value = "create collection first";
    return;
  }
  try {
    const kbVersion = await createKbVersion(createdCollectionId.value, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      version_name: kbVersionName.value,
      status: "released",
    });
    createdKbVersionId.value = kbVersion.id;
    message.value = `kb version created: ${kbVersion.id}`;
  } catch (error) {
    errorMessage.value = `create kb version failed: ${stringifyError(error)}`;
  }
}

async function onCreatePersonaPack(): Promise<void> {
  clearNotice();
  try {
    const personaPack = await createPersonaPack({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      name: personaPackName.value,
    });
    createdPersonaPackId.value = personaPack.id;
    message.value = `persona pack created: ${personaPack.id}`;
  } catch (error) {
    errorMessage.value = `create persona pack failed: ${stringifyError(error)}`;
  }
}

async function onCreatePersonaVersion(): Promise<void> {
  clearNotice();
  if (!createdPersonaPackId.value) {
    errorMessage.value = "create persona pack first";
    return;
  }
  try {
    const version = await createPersonaVersion(createdPersonaPackId.value, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      version_name: personaVersionName.value,
      style_json: { tone: "cinematic", style: "director-a" },
    });
    createdPersonaVersionId.value = version.id;
    message.value = `persona version created: ${version.id}`;
  } catch (error) {
    errorMessage.value = `create persona version failed: ${stringifyError(error)}`;
  }
}

async function onBindPersona(): Promise<void> {
  clearNotice();
  if (!createdPersonaVersionId.value || !createdCollectionId.value || !createdKbVersionId.value) {
    errorMessage.value = "need persona version + collection + kb version";
    return;
  }
  try {
    await bindPersonaResources(createdPersonaVersionId.value, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      dataset_collection_ids: [createdCollectionId.value],
      kb_version_ids: [createdKbVersionId.value],
      binding_role: "primary",
    });
    message.value = "persona bindings updated";
  } catch (error) {
    errorMessage.value = `bind persona failed: ${stringifyError(error)}`;
  }
}

async function onPreviewPersona(): Promise<void> {
  clearNotice();
  if (!createdPersonaVersionId.value) {
    errorMessage.value = "create persona version first";
    return;
  }
  try {
    const preview = await previewPersona({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      persona_pack_version_id: createdPersonaVersionId.value,
      query: personaQuery.value,
      top_k: 5,
    });
    personaPreviewText.value = toPrettyJson(preview);
  } catch (error) {
    errorMessage.value = `persona preview failed: ${stringifyError(error)}`;
  }
}

async function onCreateCulturePack(): Promise<void> {
  clearNotice();
  try {
    await createCulturePack({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      culture_pack_id: culturePackId.value,
      display_name: cultureDisplayName.value,
      constraints: parseJsonObject(cultureConstraintsJson.value),
    });
    message.value = "culture pack created";
  } catch (error) {
    errorMessage.value = `create culture pack failed: ${stringifyError(error)}`;
  }
}

async function onExportCulturePack(): Promise<void> {
  clearNotice();
  try {
    const exported = await exportCulturePack({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      culture_pack_id: culturePackId.value,
    });
    cultureExportText.value = toPrettyJson(exported);
  } catch (error) {
    errorMessage.value = `export culture pack failed: ${stringifyError(error)}`;
  }
}

onMounted(() => {
  void onLoadLanguageSettings();
});
</script>
