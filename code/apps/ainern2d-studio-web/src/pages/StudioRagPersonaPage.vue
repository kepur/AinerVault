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
        <NButton type="primary" @click="onInitDefaults">{{ t('common.init') }}</NButton>
        <NButton @click="onReloadAll">{{ t('common.refresh') }}</NButton>
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
      <!-- 绑定区域 -->
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive style="margin-bottom: 12px;">
        <NGridItem span="0:2 900:1">
          <NFormItem label="绑定类型">
            <NSelect
              v-model:value="collectionBindType"
              :options="bindTypeOptions"
              placeholder="选择绑定类型"
              clearable
            />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 900:1">
          <NFormItem label="绑定对象">
            <NSelect
              v-model:value="collectionBindId"
              :options="bindTargetOptions"
              placeholder="选择绑定对象"
              clearable
              filterable
              :disabled="!collectionBindType"
            />
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
          <NFormItem label="关联职业 (Role ID)">
            <NSelect
              v-model:value="personaRoleId"
              :options="roleOptions"
              placeholder="选择职业（继承 Role KB）"
              clearable
              filterable
            />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Persona Version Name">
            <NInput v-model:value="personaVersionName" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 900:1">
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

    <!-- 文档上传 RAG 导入 -->
    <NCard title="文档上传 → RAG 导入（PDF/DOCX/XLSX/TXT）">
      <NGrid :cols="3" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Provider（多模态LLM，可选）">
            <NSelect
              v-model:value="binaryImportProviderId"
              :options="providerOptions"
              placeholder="留空则直接解析文本"
              clearable
              filterable
            />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="启用视觉解析">
            <NSwitch v-model:value="binaryImportUseVision" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="选择文件">
            <input ref="fileInputRef" type="file" accept=".pdf,.docx,.xlsx,.xls,.txt" @change="onFileSelected" style="width: 100%" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NSpace>
        <NButton
          type="primary"
          :loading="isUploadingFile"
          :disabled="!selectedCollectionId || !selectedFile || isUploadingFile"
          @click="onUploadFile"
        >
          {{ isUploadingFile ? '上传解析中...' : '上传并导入到 RAG' }}
        </NButton>
        <NTag v-if="!selectedCollectionId" type="warning" size="small">请先选择 Collection</NTag>
        <NTag v-if="selectedFile" type="info" size="small">{{ selectedFile.name }}</NTag>
      </NSpace>
      <div v-if="binaryImportResult" style="margin-top: 10px;">
        <NTag type="success" :bordered="false">
          ✓ 导入完成：{{ binaryImportResult.file_name }}（{{ binaryImportResult.extracted_pages }} 页，{{ binaryImportResult.extracted_tables }} 表格）
        </NTag>
        <pre v-if="binaryImportResult.extracted_text_preview" style="font-size: 12px; background: #f5f5f5; padding: 8px; margin-top: 6px; border-radius: 4px;">{{ binaryImportResult.extracted_text_preview }}</pre>
      </div>
    </NCard>

    <!-- Novel RAG 一键初始化 -->
    <NCard title="小说 RAG 一键初始化">
      <NGrid :cols="3" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Novel ID">
            <NInput v-model:value="ragInitNovelId" placeholder="输入小说 ID" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Provider (LLM)">
            <NSelect
              v-model:value="ragInitProviderId"
              :options="providerOptions"
              placeholder="选择 Model Provider"
              clearable
              filterable
            />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Max Tokens">
            <NInput v-model:value="ragInitMaxTokens" placeholder="1200" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NSpace>
        <NButton
          type="primary"
          :loading="isInitingRag"
          :disabled="!selectedCollectionId || !ragInitNovelId || !ragInitProviderId || isInitingRag"
          @click="onInitNovelRag"
        >
          {{ isInitingRag ? 'RAG 初始化中...' : '一键初始化小说 RAG' }}
        </NButton>
        <NTag v-if="!selectedCollectionId" type="warning" size="small">请先选择 Collection</NTag>
      </NSpace>
      <NTag v-if="novelRagInitResult" type="success" :bordered="false" style="margin-top: 8px;">
        ✓ 已创建文档: {{ novelRagInitResult.documents_created }}，共 {{ novelRagInitResult.chunks_total }} 个 chunks
      </NTag>
    </NCard>

    <NAlert v-if="message" type="success" :show-icon="true">{{ message }}</NAlert>
    <NAlert v-if="errorMessage" type="error" :show-icon="true">{{ errorMessage }}</NAlert>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref, watch } from "vue";
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
  NTag,
  type DataTableColumns,
} from "naive-ui";
import { useI18n } from "@/composables/useI18n";


import {
  type BinaryImportJobResponse,
  type KbVersionResponse,
  type NovelRagInitResponse,
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
  initNovelRag,
  listKbVersions,
  listNovels,
  listPersonaPacks,
  listPersonaVersions,
  listProviders,
  listRagCollections,
  listRoleProfiles,
  previewPersona,
  uploadBinaryFileForImport,
} from "@/api/product";

const { t } = useI18n();

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

// 绑定区域状态
const collectionBindType = ref<string | null>(null);
const collectionBindId = ref<string | null>(null);

// 动态加载的绑定目标数据
const roleList = ref<{ role_id: string; label: string }[]>([]);
const personaList = ref<{ id: string; name: string }[]>([]);
const novelList = ref<{ id: string; title: string }[]>([]);

// Provider 下拉框数据
const providerList = ref<{ id: string; name: string }[]>([]);

const personaPackName = ref("director_A");
const personaVersionName = ref("v1");
const personaQuery = ref("sword tavern");
const personaRoleId = ref<string | null>(null);
const personaPacks = ref<PersonaPackResponse[]>([]);
const personaVersions = ref<PersonaVersionResponse[]>([]);
const selectedPersonaPackId = ref("");
const selectedPersonaVersionId = ref("");

const previewText = ref("{}");
const message = ref("");
const errorMessage = ref("");

// Novel RAG 初始化状态
const ragInitNovelId = ref("");
const ragInitProviderId = ref<string | null>(null);
const ragInitMaxTokens = ref("1200");
const isInitingRag = ref(false);
const novelRagInitResult = ref<NovelRagInitResponse | null>(null);

// 文档上传状态
const binaryImportProviderId = ref<string | null>(null);
const binaryImportUseVision = ref(false);
const selectedFile = ref<File | null>(null);
const fileInputRef = ref<HTMLInputElement | null>(null);
const isUploadingFile = ref(false);
const binaryImportResult = ref<BinaryImportJobResponse | null>(null);

// ── 下拉框选项 ──
const bindTypeOptions = [
  { label: "Role（职业基座知识库）", value: "role" },
  { label: "Persona（个人风格知识库）", value: "persona" },
  { label: "Novel（项目小说知识库）", value: "novel" },
  { label: "Global（全局知识库）", value: "global" },
];

const roleOptions = computed(() =>
  roleList.value.map(r => ({ label: r.label || r.role_id, value: r.role_id }))
);

const providerOptions = computed(() =>
  providerList.value.map(p => ({ label: p.name, value: p.id }))
);

const bindTargetOptions = computed(() => {
  const bt = collectionBindType.value;
  if (bt === "role") return roleList.value.map(r => ({ label: r.label || r.role_id, value: r.role_id }));
  if (bt === "persona") return personaList.value.map(p => ({ label: p.name, value: p.id }));
  if (bt === "novel") return novelList.value.map(n => ({ label: n.title || n.id, value: n.id }));
  if (bt === "global") return [{ label: "(全局)", value: "global" }];
  return [];
});

// 绑定类型变更时清空绑定对象
watch(collectionBindType, () => {
  collectionBindId.value = null;
});

function onFileSelected(event: Event): void {
  const target = event.target as HTMLInputElement;
  selectedFile.value = target.files?.[0] ?? null;
}

const collectionColumns: DataTableColumns<RagCollectionResponse> = [
  { title: "ID", key: "id", width: 200, ellipsis: { tooltip: true } },
  { title: "Name", key: "name" },
  { title: "Lang", key: "language_code", width: 60 },
  {
    title: "Bound To",
    key: "bind_type",
    width: 180,
    render: (row) => {
      if (!row.bind_type) return "—";
      const label = row.bind_type === "global" ? "Global" : `${row.bind_type}:${row.bind_id || "?"}`;
      return h(NTag, { size: "small", type: "info", bordered: false }, { default: () => label });
    },
  },
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
    title: "Role",
    key: "role_id",
    width: 120,
    render: (row) => row.role_id ? h(NTag, { size: "small", bordered: false }, { default: () => row.role_id }) : "—",
  },
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

// ── 加载下拉数据 ──
async function loadDropdownData(): Promise<void> {
  try {
    const [roles, providers, novels, personas] = await Promise.all([
      listRoleProfiles({ tenant_id: tenantId.value, project_id: projectId.value }).catch(() => []),
      listProviders(tenantId.value, projectId.value).catch(() => []),
      listNovels(tenantId.value, projectId.value).catch(() => []),
      listPersonaPacks({ tenant_id: tenantId.value, project_id: projectId.value }).catch(() => []),
    ]);
    roleList.value = (roles as { role_id: string; prompt_style?: string }[]).map(r => ({
      role_id: r.role_id,
      label: r.role_id,
    }));
    providerList.value = (providers as { id: string; name: string }[]).map(p => ({
      id: p.id,
      name: p.name,
    }));
    novelList.value = (novels as { id: string; title: string }[]).map(n => ({
      id: n.id,
      title: n.title || n.id,
    }));
    personaList.value = (personas as PersonaPackResponse[]).map(p => ({
      id: p.id,
      name: p.name,
    }));
  } catch {
    // silent
  }
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
      bind_type: collectionBindType.value || undefined,
      bind_id: collectionBindId.value || undefined,
    });
    selectedCollectionId.value = collection.id;
    await onListCollections();
    message.value = `collection created: ${collection.id} (bind: ${collection.bind_type || "none"})`;
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
      role_id: personaRoleId.value || undefined,
    });
    selectedPersonaPackId.value = pack.id;
    await onListPersonaPacks();
    message.value = `persona pack created: ${pack.id} (role: ${pack.role_id || "none"})`;
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
  await loadDropdownData();
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

async function onUploadFile(): Promise<void> {
  clearNotice();
  if (!selectedCollectionId.value || !selectedFile.value) {
    errorMessage.value = "请选择 Collection 和文件";
    return;
  }
  isUploadingFile.value = true;
  try {
    binaryImportResult.value = await uploadBinaryFileForImport(
      selectedCollectionId.value,
      selectedFile.value,
      {
        tenant_id: tenantId.value,
        project_id: projectId.value,
        model_provider_id: binaryImportProviderId.value || undefined,
        use_vision: binaryImportUseVision.value,
      }
    );
    message.value = `文件导入完成：${binaryImportResult.value.file_name}`;
    selectedFile.value = null;
    if (fileInputRef.value) fileInputRef.value.value = "";
  } catch (error) {
    errorMessage.value = `文件上传失败: ${stringifyError(error)}`;
  } finally {
    isUploadingFile.value = false;
  }
}

async function onInitNovelRag(): Promise<void> {
  clearNotice();
  if (!selectedCollectionId.value || !ragInitNovelId.value || !ragInitProviderId.value) {
    errorMessage.value = "请填写小说ID、Provider ID，并选择Collection";
    return;
  }
  isInitingRag.value = true;
  try {
    novelRagInitResult.value = await initNovelRag(selectedCollectionId.value, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      model_provider_id: ragInitProviderId.value,
      novel_id: ragInitNovelId.value,
      max_tokens: parseInt(ragInitMaxTokens.value) || 1200,
    });
    message.value = `RAG 初始化完成：${novelRagInitResult.value.documents_created} 个章节，共 ${novelRagInitResult.value.chunks_total} 个 chunks`;
  } catch (error) {
    errorMessage.value = `RAG 初始化失败: ${stringifyError(error)}`;
  } finally {
    isInitingRag.value = false;
  }
}

onMounted(() => {
  void onReloadAll();
});
</script>
