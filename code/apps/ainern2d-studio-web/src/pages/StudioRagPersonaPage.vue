<template>
  <div class="page-grid">
    <NCard title="SKILL 26 · RAG / Persona（导演A/B/C）">
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
          <NFormItem label="过滤关键字">
            <NInput v-model:value="keyword" placeholder="name keyword" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NSpace>
        <NButton type="primary" @click="onInitDefaults">初始化导演/数据集</NButton>
        <NButton @click="onReloadAll">刷新全部</NButton>
      </NSpace>
    </NCard>

    <NCard title="Dataset / Collection CRUD">
      <NGrid :cols="3" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Collection Name">
            <NInput v-model:value="collectionName" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Language">
            <NInput v-model:value="collectionLanguage" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="KB Version Name">
            <NInput v-model:value="kbVersionName" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NSpace>
        <NButton type="primary" @click="onCreateCollection">新增 Collection</NButton>
        <NButton type="warning" :disabled="!selectedCollectionId" @click="onCreateKbVersion">新增 KB Version</NButton>
      </NSpace>
      <NTag type="info" :bordered="false">Selected Collection: {{ selectedCollectionId || "(none)" }}</NTag>
      <NDataTable :columns="collectionColumns" :data="collections" :pagination="{ pageSize: 6 }" />
      <NDataTable :columns="kbColumns" :data="kbVersions" :pagination="{ pageSize: 6 }" />
    </NCard>

    <NCard title="Persona（导演）CRUD + Binding + Preview">
      <NGrid :cols="3" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Persona Pack Name">
            <NInput v-model:value="personaPackName" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Persona Version Name">
            <NInput v-model:value="personaVersionName" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Preview Query">
            <NInput v-model:value="personaQuery" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NSpace>
        <NButton type="primary" @click="onCreatePersonaPack">新增 Persona Pack</NButton>
        <NButton :disabled="!selectedPersonaPackId" @click="onCreatePersonaVersion">新增 Persona Version</NButton>
        <NButton type="warning" :disabled="!selectedPersonaVersionId || !selectedCollectionId || !selectedKbVersionId" @click="onBindPersona">绑定数据集</NButton>
        <NButton type="info" :disabled="!selectedPersonaVersionId" @click="onPreviewPersona">Preview</NButton>
      </NSpace>
      <NSpace>
        <NTag type="info" :bordered="false">Pack: {{ selectedPersonaPackId || "(none)" }}</NTag>
        <NTag type="success" :bordered="false">Version: {{ selectedPersonaVersionId || "(none)" }}</NTag>
      </NSpace>
      <NDataTable :columns="personaPackColumns" :data="personaPacks" :pagination="{ pageSize: 6 }" />
      <NDataTable :columns="personaVersionColumns" :data="personaVersions" :pagination="{ pageSize: 6 }" />
      <pre class="json-panel">{{ previewText }}</pre>
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
  NFormItem,
  NGrid,
  NGridItem,
  NInput,
  NSpace,
  NTag,
  type DataTableColumns,
} from "naive-ui";

import {
  type KbVersionResponse,
  type PersonaPackResponse,
  type PersonaVersionResponse,
  type RagCollectionResponse,
  bindPersonaResources,
  createKbVersion,
  createPersonaPack,
  createPersonaVersion,
  createRagCollection,
  deletePersonaPack,
  deleteRagCollection,
  listKbVersions,
  listPersonaPacks,
  listPersonaVersions,
  listRagCollections,
  previewPersona,
} from "@/api/product";

const tenantId = ref("default");
const projectId = ref("default");
const keyword = ref("");

const collectionName = ref("dataset_main");
const collectionLanguage = ref("zh");
const kbVersionName = ref("v1");
const collections = ref<RagCollectionResponse[]>([]);
const kbVersions = ref<KbVersionResponse[]>([]);
const selectedCollectionId = ref("");
const selectedKbVersionId = ref("");

const personaPackName = ref("director_A");
const personaVersionName = ref("v1");
const personaQuery = ref("sword tavern");
const personaPacks = ref<PersonaPackResponse[]>([]);
const personaVersions = ref<PersonaVersionResponse[]>([]);
const selectedPersonaPackId = ref("");
const selectedPersonaVersionId = ref("");

const previewText = ref("{}");
const message = ref("");
const errorMessage = ref("");

const collectionColumns: DataTableColumns<RagCollectionResponse> = [
  { title: "ID", key: "id" },
  { title: "Name", key: "name" },
  { title: "Lang", key: "language_code" },
  {
    title: "Action",
    key: "action",
    render: (row) =>
      h(NSpace, { size: 6 }, {
        default: () => [
          h(NButton, { size: "tiny", onClick: () => {
            selectedCollectionId.value = row.id;
            void onListKbVersions();
          } }, { default: () => "Use" }),
          h(NButton, { size: "tiny", type: "error", onClick: () => void onDeleteCollection(row.id) }, { default: () => "Delete" }),
        ],
      }),
  },
];

const kbColumns: DataTableColumns<KbVersionResponse> = [
  { title: "ID", key: "id" },
  { title: "Version", key: "version_name" },
  { title: "Status", key: "status" },
  {
    title: "Action",
    key: "action",
    render: (row) =>
      h(NButton, { size: "tiny", onClick: () => {
        selectedKbVersionId.value = row.id;
      } }, { default: () => "Use" }),
  },
];

const personaPackColumns: DataTableColumns<PersonaPackResponse> = [
  { title: "ID", key: "id" },
  { title: "Name", key: "name" },
  {
    title: "Action",
    key: "action",
    render: (row) =>
      h(NSpace, { size: 6 }, {
        default: () => [
          h(NButton, { size: "tiny", onClick: () => {
            selectedPersonaPackId.value = row.id;
            void onListPersonaVersions();
          } }, { default: () => "Use" }),
          h(NButton, { size: "tiny", type: "error", onClick: () => void onDeletePersonaPack(row.id) }, { default: () => "Delete" }),
        ],
      }),
  },
];

const personaVersionColumns: DataTableColumns<PersonaVersionResponse> = [
  { title: "ID", key: "id" },
  { title: "Version", key: "version_name" },
  {
    title: "Action",
    key: "action",
    render: (row) =>
      h(NButton, { size: "tiny", onClick: () => {
        selectedPersonaVersionId.value = row.id;
      } }, { default: () => "Use" }),
  },
];

function stringifyError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function clearNotice(): void {
  message.value = "";
  errorMessage.value = "";
}

async function onListCollections(): Promise<void> {
  clearNotice();
  try {
    collections.value = await listRagCollections({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      keyword: keyword.value || undefined,
    });
  } catch (error) {
    errorMessage.value = `list collections failed: ${stringifyError(error)}`;
  }
}

async function onListKbVersions(): Promise<void> {
  clearNotice();
  if (!selectedCollectionId.value) {
    kbVersions.value = [];
    return;
  }
  try {
    kbVersions.value = await listKbVersions(selectedCollectionId.value);
  } catch (error) {
    errorMessage.value = `list kb versions failed: ${stringifyError(error)}`;
  }
}

async function onCreateCollection(): Promise<void> {
  clearNotice();
  try {
    const collection = await createRagCollection({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      name: collectionName.value,
      language_code: collectionLanguage.value,
    });
    selectedCollectionId.value = collection.id;
    await onListCollections();
    message.value = `collection created: ${collection.id}`;
  } catch (error) {
    errorMessage.value = `create collection failed: ${stringifyError(error)}`;
  }
}

async function onDeleteCollection(collectionId: string): Promise<void> {
  clearNotice();
  try {
    await deleteRagCollection(collectionId, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
    });
    if (selectedCollectionId.value === collectionId) {
      selectedCollectionId.value = "";
      selectedKbVersionId.value = "";
      kbVersions.value = [];
    }
    await onListCollections();
    message.value = `collection deleted: ${collectionId}`;
  } catch (error) {
    errorMessage.value = `delete collection failed: ${stringifyError(error)}`;
  }
}

async function onCreateKbVersion(): Promise<void> {
  clearNotice();
  if (!selectedCollectionId.value) {
    errorMessage.value = "select collection first";
    return;
  }
  try {
    const kb = await createKbVersion(selectedCollectionId.value, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      version_name: kbVersionName.value,
      status: "released",
    });
    selectedKbVersionId.value = kb.id;
    await onListKbVersions();
    message.value = `kb version created: ${kb.id}`;
  } catch (error) {
    errorMessage.value = `create kb version failed: ${stringifyError(error)}`;
  }
}

async function onListPersonaPacks(): Promise<void> {
  clearNotice();
  try {
    personaPacks.value = await listPersonaPacks({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      keyword: keyword.value || undefined,
    });
  } catch (error) {
    errorMessage.value = `list persona packs failed: ${stringifyError(error)}`;
  }
}

async function onListPersonaVersions(): Promise<void> {
  clearNotice();
  if (!selectedPersonaPackId.value) {
    personaVersions.value = [];
    return;
  }
  try {
    personaVersions.value = await listPersonaVersions(selectedPersonaPackId.value);
  } catch (error) {
    errorMessage.value = `list persona versions failed: ${stringifyError(error)}`;
  }
}

async function onCreatePersonaPack(): Promise<void> {
  clearNotice();
  try {
    const pack = await createPersonaPack({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      name: personaPackName.value,
    });
    selectedPersonaPackId.value = pack.id;
    await onListPersonaPacks();
    message.value = `persona pack created: ${pack.id}`;
  } catch (error) {
    errorMessage.value = `create persona pack failed: ${stringifyError(error)}`;
  }
}

async function onDeletePersonaPack(personaPackId: string): Promise<void> {
  clearNotice();
  try {
    await deletePersonaPack(personaPackId, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
    });
    if (selectedPersonaPackId.value === personaPackId) {
      selectedPersonaPackId.value = "";
      selectedPersonaVersionId.value = "";
      personaVersions.value = [];
    }
    await onListPersonaPacks();
    message.value = `persona pack deleted: ${personaPackId}`;
  } catch (error) {
    errorMessage.value = `delete persona pack failed: ${stringifyError(error)}`;
  }
}

async function onCreatePersonaVersion(): Promise<void> {
  clearNotice();
  if (!selectedPersonaPackId.value) {
    errorMessage.value = "select persona pack first";
    return;
  }
  try {
    const version = await createPersonaVersion(selectedPersonaPackId.value, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      version_name: personaVersionName.value,
      style_json: { tone: "cinematic" },
    });
    selectedPersonaVersionId.value = version.id;
    await onListPersonaVersions();
    message.value = `persona version created: ${version.id}`;
  } catch (error) {
    errorMessage.value = `create persona version failed: ${stringifyError(error)}`;
  }
}

async function onBindPersona(): Promise<void> {
  clearNotice();
  if (!selectedPersonaVersionId.value || !selectedCollectionId.value || !selectedKbVersionId.value) {
    errorMessage.value = "select persona version + collection + kb version first";
    return;
  }
  try {
    await bindPersonaResources(selectedPersonaVersionId.value, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      dataset_collection_ids: [selectedCollectionId.value],
      kb_version_ids: [selectedKbVersionId.value],
      binding_role: "primary",
    });
    message.value = "persona binding updated";
  } catch (error) {
    errorMessage.value = `bind persona failed: ${stringifyError(error)}`;
  }
}

async function onPreviewPersona(): Promise<void> {
  clearNotice();
  if (!selectedPersonaVersionId.value) {
    errorMessage.value = "select persona version first";
    return;
  }
  try {
    const preview = await previewPersona({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      persona_pack_version_id: selectedPersonaVersionId.value,
      query: personaQuery.value,
      top_k: 5,
    });
    previewText.value = JSON.stringify(preview, null, 2);
    message.value = "persona preview loaded";
  } catch (error) {
    errorMessage.value = `preview failed: ${stringifyError(error)}`;
  }
}

async function onReloadAll(): Promise<void> {
  await onListCollections();
  await onListPersonaPacks();
  if (selectedCollectionId.value) {
    await onListKbVersions();
  }
  if (selectedPersonaPackId.value) {
    await onListPersonaVersions();
  }
}

async function onInitDefaults(): Promise<void> {
  clearNotice();
  try {
    collectionName.value = "director_dataset_a";
    personaPackName.value = "director_A";
    await onCreateCollection();
    kbVersionName.value = "v1";
    await onCreateKbVersion();
    await onCreatePersonaPack();
    personaVersionName.value = "v1";
    await onCreatePersonaVersion();
    await onBindPersona();
    await onReloadAll();
    message.value = "default director resources initialized";
  } catch (error) {
    errorMessage.value = `init defaults failed: ${stringifyError(error)}`;
  }
}

onMounted(() => {
  void onReloadAll();
});
</script>
