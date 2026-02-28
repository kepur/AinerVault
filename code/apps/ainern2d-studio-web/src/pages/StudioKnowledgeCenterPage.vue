<template>
  <div class="page-grid">
    <NCard title="知识资产中心">
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 900:1">
          <NFormItem label="Tenant ID"><NInput v-model:value="tenantId" /></NFormItem>
        </NGridItem>
        <NGridItem span="0:2 900:1">
          <NFormItem label="Project ID"><NInput v-model:value="projectId" /></NFormItem>
        </NGridItem>
      </NGrid>
    </NCard>

    <NTabs v-model:value="activeTab" type="card" animated>

      <!-- ═══ Tab 1: 集合管理 ═══ -->
      <NTabPane name="collections" :tab="t('kb.collections')">
        <NCard>
          <NGrid :cols="3" :x-gap="8" :y-gap="8" responsive="screen" item-responsive>
            <NGridItem span="0:3 900:1">
              <NFormItem label="集合名称"><NInput v-model:value="collectionName" /></NFormItem>
            </NGridItem>
            <NGridItem span="0:3 900:1">
              <NFormItem label="语言">
                <NSelect v-model:value="collectionLanguage" :options="languageOptions" />
              </NFormItem>
            </NGridItem>
            <NGridItem span="0:3 900:1">
              <NFormItem label="描述"><NInput v-model:value="collectionDescription" /></NFormItem>
            </NGridItem>
          </NGrid>
          <NSpace>
            <NButton type="primary" @click="onCreateCollection">新增集合</NButton>
            <NButton @click="onLoadCollections">{{ t('common.refresh') }}</NButton>
          </NSpace>
          <NDivider />
          <NDataTable :columns="collectionColumns" :data="collections" :pagination="{ pageSize: 8 }" />
        </NCard>
      </NTabPane>

      <!-- ═══ Tab 2: KB 版本 ═══ -->
      <NTabPane name="versions" :tab="t('kb.versions')">
        <NCard>
          <NFormItem label="选择集合">
            <NSelect
              v-model:value="selectedCollectionId"
              :options="collectionOptions"
              placeholder="选择一个集合"
              filterable
              @update:value="onLoadKbVersions"
            />
          </NFormItem>
          <NGrid :cols="2" :x-gap="8" :y-gap="8" responsive="screen" item-responsive>
            <NGridItem span="0:2 900:1">
              <NFormItem label="版本名称"><NInput v-model:value="kbVersionName" placeholder="v1" /></NFormItem>
            </NGridItem>
            <NGridItem span="0:2 900:1">
              <NFormItem label="嵌入模型">
                <NInput v-model:value="kbEmbeddingModel" placeholder="text-embedding-ada-002" />
              </NFormItem>
            </NGridItem>
          </NGrid>
          <NButton type="primary" :disabled="!selectedCollectionId" @click="onCreateKbVersion">新增版本</NButton>
          <NDivider />
          <NDataTable :columns="kbVersionColumns" :data="kbVersions" :pagination="{ pageSize: 6 }" />
        </NCard>
      </NTabPane>

      <!-- ═══ Tab 3: 文档导入 ═══ -->
      <NTabPane name="import" :tab="t('kb.docImport')">
        <NCard>
          <NFormItem label="选择集合">
            <NSelect
              v-model:value="importCollectionId"
              :options="collectionOptions"
              placeholder="选择目标集合"
              filterable
            />
          </NFormItem>
          <NGrid :cols="2" :x-gap="8" :y-gap="8" responsive="screen" item-responsive>
            <NGridItem span="0:2 900:1">
              <NFormItem label="Provider ID（多模态 LLM，可选）">
                <NInput v-model:value="importProviderId" placeholder="留空则直接解析文本" />
              </NFormItem>
            </NGridItem>
            <NGridItem span="0:2 900:1">
              <NFormItem label="视觉解析">
                <NSwitch v-model:value="importUseVision" />
              </NFormItem>
            </NGridItem>
          </NGrid>
          <NFormItem label="选择文件（PDF / DOCX / XLSX / TXT）">
            <input
              ref="fileInputRef"
              type="file"
              accept=".pdf,.docx,.xlsx,.xls,.txt"
              style="width: 100%"
              @change="onFileSelected"
            />
          </NFormItem>
          <NSpace>
            <NButton
              type="primary"
              :loading="isUploading"
              :disabled="!importCollectionId || !selectedFile || isUploading"
              @click="onUploadFile"
            >
              {{ isUploading ? "上传解析中..." : "上传并导入" }}
            </NButton>
            <NTag v-if="selectedFile" type="info" size="small">{{ selectedFile.name }}</NTag>
            <NTag v-if="!importCollectionId" type="warning" size="small">请先选择集合</NTag>
          </NSpace>
          <div v-if="importResult" style="margin-top:12px">
            <NTag type="success" :bordered="false">
              ✓ {{ importResult.file_name }}（{{ importResult.extracted_pages }} 页，{{ importResult.extracted_tables }} 表格）
            </NTag>
            <pre v-if="importResult.extracted_text_preview" class="json-panel" style="margin-top:6px">{{ importResult.extracted_text_preview }}</pre>
          </div>
        </NCard>
      </NTabPane>

      <!-- ═══ Tab 4: 知识包初始化 ═══ -->
      <NTabPane name="bootstrap" tab="知识包初始化">
        <NCard>
          <NGrid :cols="2" :x-gap="8" :y-gap="8" responsive="screen" item-responsive>
            <NGridItem span="0:2 900:1">
              <NFormItem label="Role ID（职业）">
                <NSelect
                  v-model:value="bootstrapRoleId"
                  :options="roleOptions"
                  placeholder="选择职业"
                  filterable
                />
              </NFormItem>
            </NGridItem>
            <NGridItem span="0:2 900:1">
              <NFormItem label="包名称">
                <NInput v-model:value="bootstrapPackName" placeholder="director_knowledge_pack" />
              </NFormItem>
            </NGridItem>
            <NGridItem span="0:2 900:1">
              <NFormItem label="初始化模板">
                <NSelect v-model:value="bootstrapTemplateKey" :options="bootstrapTemplateOptions" />
              </NFormItem>
            </NGridItem>
            <NGridItem span="0:2 900:1">
              <NFormItem label="语言">
                <NSelect v-model:value="bootstrapLanguage" :options="languageOptions" />
              </NFormItem>
            </NGridItem>
            <NGridItem span="0:2 900:1">
              <NFormItem label="知识作用域">
                <NSelect v-model:value="bootstrapScope" :options="scopeOptions" />
              </NFormItem>
            </NGridItem>
          </NGrid>
          <NButton
            type="primary"
            :loading="isBootstrapping"
            :disabled="!bootstrapRoleId || isBootstrapping"
            @click="onBootstrap"
          >
            {{ isBootstrapping ? "初始化中..." : "一键初始化知识包" }}
          </NButton>
          <pre v-if="bootstrapResult" class="json-panel" style="margin-top:12px">{{ bootstrapResult }}</pre>
        </NCard>
      </NTabPane>
    </NTabs>

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
  NDivider,
  NFormItem,
  NGrid,
  NGridItem,
  NInput,
  NSelect,
  NSpace,
  NSwitch,
  NTabPane,
  NTabs,
  NTag,
  type DataTableColumns,
} from "naive-ui";
import { useI18n } from "@/composables/useI18n";


import {
  bootstrapKnowledgePack,
  createKbVersion,
  createRagCollection,
  deleteRagCollection,
  listKbVersions,
  listProviders,
  listRagCollections,
  listRoleProfiles,
  uploadBinaryFileForImport,
  type BinaryImportJobResponse,
  type KbVersionResponse,
  type KnowledgePackBootstrapResponse,
  type RagCollectionResponse,
  type RoleProfileResponse,
} from "@/api/product";

const { t } = useI18n();

const tenantId = ref("default");
const projectId = ref("default");
const activeTab = ref("collections");

// Collections
const collectionName = ref("dataset_main");
const collectionLanguage = ref("zh-CN");
const collectionDescription = ref("");
const collections = ref<RagCollectionResponse[]>([]);

// KB Versions
const selectedCollectionId = ref<string | null>(null);
const kbVersionName = ref("v1");
const kbEmbeddingModel = ref("");
const kbVersions = ref<KbVersionResponse[]>([]);

// Import
const importCollectionId = ref<string | null>(null);
const importProviderId = ref("");
const importUseVision = ref(false);
const selectedFile = ref<File | null>(null);
const fileInputRef = ref<HTMLInputElement | null>(null);
const isUploading = ref(false);
const importResult = ref<BinaryImportJobResponse | null>(null);

// Bootstrap
const roleProfiles = ref<RoleProfileResponse[]>([]);
const bootstrapRoleId = ref<string | null>(null);
const bootstrapPackName = ref("director_knowledge_pack");
const bootstrapTemplateKey = ref("director_bootstrap_v1");
const bootstrapLanguage = ref("zh-CN");
const bootstrapScope = ref("style_rule");
const isBootstrapping = ref(false);
const bootstrapResult = ref("");

const message = ref("");
const errorMessage = ref("");

const languageOptions = [
  { label: "简体中文 (zh-CN)", value: "zh-CN" },
  { label: "English (en-US)", value: "en-US" },
  { label: "日本語 (ja-JP)", value: "ja-JP" },
  { label: "한국어 (ko-KR)", value: "ko-KR" },
];

const scopeOptions = [
  { label: "style_rule（风格规则）", value: "style_rule" },
  { label: "novel（小说知识）", value: "novel" },
  { label: "chapter（章节知识）", value: "chapter" },
  { label: "visual_grammar（视觉语法）", value: "visual_grammar" },
];

const bootstrapTemplateOptions = [
  { label: "director_bootstrap_v1", value: "director_bootstrap_v1" },
  { label: "visual_grammar", value: "visual_grammar" },
  { label: "wuxia_style", value: "wuxia_style" },
  { label: "i18n_pack", value: "i18n_pack" },
  { label: "culture_enforcer", value: "culture_enforcer" },
];

const collectionOptions = computed(() =>
  collections.value.map(c => ({ label: `${c.name} (${c.language_code})`, value: c.id }))
);

const roleOptions = computed(() =>
  roleProfiles.value.map(r => ({ label: r.role_id, value: r.role_id }))
);

const collectionColumns: DataTableColumns<RagCollectionResponse> = [
  { title: "名称", key: "name" },
  { title: "语言", key: "language_code", width: 100 },
  { title: "ID", key: "id", ellipsis: true },
  {
    title: "操作",
    key: "action",
    width: 160,
    render: (row) =>
      h(NButton, {
        size: "tiny",
        type: "error",
        onClick: () => void onDeleteCollection(row.id),
      }, { default: () => "删除" }),
  },
];

const kbVersionColumns: DataTableColumns<KbVersionResponse> = [
  { title: "版本", key: "version_name" },
  { title: "状态", key: "status", width: 100 },
  { title: "ID", key: "id", ellipsis: true },
];

function stringifyError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function clearNotice(): void {
  message.value = "";
  errorMessage.value = "";
}

function onFileSelected(event: Event): void {
  const target = event.target as HTMLInputElement;
  selectedFile.value = target.files?.[0] ?? null;
}

async function onLoadCollections(): Promise<void> {
  try {
    collections.value = await listRagCollections({ tenant_id: tenantId.value, project_id: projectId.value });
  } catch (error) {
    errorMessage.value = `load collections failed: ${stringifyError(error)}`;
  }
}

async function onCreateCollection(): Promise<void> {
  clearNotice();
  try {
    await createRagCollection({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      name: collectionName.value,
      language_code: collectionLanguage.value,
    });
    await onLoadCollections();
    message.value = `集合已创建: ${collectionName.value}`;
  } catch (error) {
    errorMessage.value = `create collection failed: ${stringifyError(error)}`;
  }
}

async function onDeleteCollection(collectionId: string): Promise<void> {
  clearNotice();
  try {
    await deleteRagCollection(collectionId, { tenant_id: tenantId.value, project_id: projectId.value });
    await onLoadCollections();
    message.value = "集合已删除";
  } catch (error) {
    errorMessage.value = `delete collection failed: ${stringifyError(error)}`;
  }
}

async function onLoadKbVersions(collectionId: string | null): Promise<void> {
  if (!collectionId) return;
  try {
    kbVersions.value = await listKbVersions(collectionId);
  } catch (error) {
    errorMessage.value = `load kb versions failed: ${stringifyError(error)}`;
  }
}

async function onCreateKbVersion(): Promise<void> {
  if (!selectedCollectionId.value) return;
  clearNotice();
  try {
    await createKbVersion(selectedCollectionId.value, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      version_name: kbVersionName.value,
    });
    await onLoadKbVersions(selectedCollectionId.value);
    message.value = `KB 版本已创建: ${kbVersionName.value}`;
  } catch (error) {
    errorMessage.value = `create kb version failed: ${stringifyError(error)}`;
  }
}

async function onUploadFile(): Promise<void> {
  if (!importCollectionId.value || !selectedFile.value) return;
  clearNotice();
  isUploading.value = true;
  try {
    importResult.value = await uploadBinaryFileForImport(
      importCollectionId.value,
      selectedFile.value,
      {
        tenant_id: tenantId.value,
        project_id: projectId.value,
        model_provider_id: importProviderId.value || undefined,
        use_vision: importUseVision.value,
      }
    );
    message.value = `导入成功: ${importResult.value.file_name}`;
  } catch (error) {
    errorMessage.value = `upload failed: ${stringifyError(error)}`;
  } finally {
    isUploading.value = false;
  }
}

async function onBootstrap(): Promise<void> {
  if (!bootstrapRoleId.value) return;
  clearNotice();
  isBootstrapping.value = true;
  try {
    const result = await bootstrapKnowledgePack({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      role_id: bootstrapRoleId.value,
      pack_name: bootstrapPackName.value || undefined,
      template_key: bootstrapTemplateKey.value || undefined,
      language_code: bootstrapLanguage.value,
      default_knowledge_scope: bootstrapScope.value,
    });
    bootstrapResult.value = JSON.stringify(result, null, 2);
    message.value = "知识包初始化完成";
  } catch (error) {
    errorMessage.value = `bootstrap failed: ${stringifyError(error)}`;
  } finally {
    isBootstrapping.value = false;
  }
}

onMounted(async () => {
  await onLoadCollections();
  try {
    roleProfiles.value = await listRoleProfiles({ tenant_id: tenantId.value, project_id: projectId.value });
  } catch {
    // non-critical
  }
});
</script>
