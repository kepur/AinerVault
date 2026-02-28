<template>
  <div class="page-grid">
    <NCard title="Role Workbench">
      <NGrid :cols="3" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Tenant ID"><NInput v-model:value="tenantId" /></NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Project ID"><NInput v-model:value="projectId" /></NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Keyword"><NInput v-model:value="keyword" placeholder="role/skill keyword" /></NFormItem>
        </NGridItem>
      </NGrid>
      <NSpace>
        <NButton type="primary" @click="onReloadRuntimeData">{{ t('common.refresh') }}</NButton>
      </NSpace>
    </NCard>

    <NCard title="Role Runtime Resolve">
      <NGrid :cols="2" :x-gap="8" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 900:1">
          <NFormItem label="Role">
            <NSelect v-model:value="resolveRoleId" :options="roleSelectOptions" filterable clearable />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 900:1">
          <NFormItem label="Skill">
            <NSelect v-model:value="resolveSkillId" :options="skillSelectOptions" filterable clearable />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NSpace>
        <NButton type="info" :disabled="!resolveRoleId || !resolveSkillId" @click="onResolveRuntime">{{ t('common.details') }}</NButton>
      </NSpace>
      <pre class="json-panel">{{ resolveText }}</pre>
    </NCard>

    <NCard title="Skill Runner">
      <NGrid :cols="2" :x-gap="8" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 900:1">
          <NFormItem label="Input Payload JSON">
            <NInput v-model:value="runInputText" type="textarea" :autosize="{ minRows: 3, maxRows: 8 }" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 900:1">
          <NFormItem label="Context JSON">
            <NInput v-model:value="runContextText" type="textarea" :autosize="{ minRows: 2, maxRows: 6 }" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NSpace>
        <NButton type="primary" :disabled="!resolveRoleId || !resolveSkillId" @click="onRunSkill">{{ t('common.submit') }}</NButton>
      </NSpace>
      <div>{{ runExecutionSummary }}</div>
      <NGrid :cols="2" :x-gap="8" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 1200:1">
          <NFormItem label="Output">
            <NInput :value="runResultText" type="textarea" :autosize="{ minRows: 4, maxRows: 10 }" readonly />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 1200:1">
          <NFormItem label="Logs / Change Report">
            <NInput :value="runLogText" type="textarea" :autosize="{ minRows: 4, maxRows: 10 }" readonly />
          </NFormItem>
        </NGridItem>
      </NGrid>
    </NCard>

    <NCard title="Knowledge Bootstrapping + Import Center">
      <NGrid :cols="3" :x-gap="8" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:3 900:1"><NFormItem label="Bootstrap Role"><NInput v-model:value="bootstrapRoleId" /></NFormItem></NGridItem>
        <NGridItem span="0:3 900:1"><NFormItem label="Pack Name"><NInput v-model:value="bootstrapPackName" /></NFormItem></NGridItem>
        <NGridItem span="0:3 900:1"><NFormItem label="Template Key"><NInput v-model:value="bootstrapTemplateKey" placeholder="director / translator / lighting" /></NFormItem></NGridItem>
        <NGridItem span="0:3 900:1"><NFormItem label="Language"><NInput v-model:value="bootstrapLanguageCode" /></NFormItem></NGridItem>
        <NGridItem span="0:3 900:1"><NFormItem label="Scope"><NInput v-model:value="bootstrapScope" /></NFormItem></NGridItem>
      </NGrid>
      <NSpace>
        <NButton type="primary" @click="onBootstrapKnowledgePack">初始化角色知识包</NButton>
      </NSpace>
      <NDataTable :columns="knowledgePackColumns" :data="knowledgePacks" :pagination="{ pageSize: 5 }" />

      <NGrid :cols="3" :x-gap="8" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:3 900:1"><NFormItem label="Collection ID"><NInput v-model:value="importCollectionId" /></NFormItem></NGridItem>
        <NGridItem span="0:3 900:1"><NFormItem label="KB Version ID"><NInput v-model:value="importKbVersionId" placeholder="optional" /></NFormItem></NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Source Format">
            <NSelect v-model:value="importSourceFormat" :options="sourceFormatOptions" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1"><NFormItem label="Source Name"><NInput v-model:value="importSourceName" /></NFormItem></NGridItem>
        <NGridItem span="0:3 900:1"><NFormItem label="Affected Roles CSV"><NInput v-model:value="importRoleIdsCsv" /></NFormItem></NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Content Text (txt/pdf/excel extracted text)">
            <NInput v-model:value="importContentText" type="textarea" :autosize="{ minRows: 4, maxRows: 8 }" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NSpace>
        <NButton type="warning" :disabled="!importCollectionId || !importSourceName" @click="onCreateImportJob">导入并增量进化</NButton>
      </NSpace>
      <NDataTable :columns="importJobColumns" :data="importJobs" :pagination="{ pageSize: 5 }" />
    </NCard>

    <NAlert v-if="message" type="success" :show-icon="true">{{ message }}</NAlert>
    <NAlert v-if="errorMessage" type="error" :show-icon="true">{{ errorMessage }}</NAlert>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
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
import { useI18n } from "@/composables/useI18n";


import {
  bootstrapKnowledgePack,
  createKnowledgeImportJob,
  listKnowledgeImportJobs,
  listKnowledgePacks,
  listRoleProfiles,
  listSkillRegistry,
  resolveRoleStudioRuntime,
  runRoleStudioSkill,
  type KnowledgeImportJobResponse,
  type KnowledgePackItemResponse,
  type RoleProfileResponse,
  type SkillRegistryResponse,
} from "@/api/product";

const { t } = useI18n();

const tenantId = ref("default");
const projectId = ref("default");
const keyword = ref("");

const roleProfiles = ref<RoleProfileResponse[]>([]);
const skillRegistryItems = ref<SkillRegistryResponse[]>([]);

const resolveRoleId = ref<string | null>(null);
const resolveSkillId = ref<string | null>(null);
const resolveText = ref("{}");
const runInputText = ref('{"chapter_id":"chapter_demo","raw_text":"hero enters tavern"}');
const runContextText = ref("{}");
const runResultText = ref("{}");
const runLogText = ref("[]");
const runExecutionSummary = ref("");

const bootstrapRoleId = ref("director");
const bootstrapPackName = ref("director_bootstrap_pack");
const bootstrapTemplateKey = ref("");
const bootstrapLanguageCode = ref("zh");
const bootstrapScope = ref("style_rule");
const knowledgePacks = ref<KnowledgePackItemResponse[]>([]);

const importCollectionId = ref("");
const importKbVersionId = ref("");
const importSourceFormat = ref("txt");
const importSourceName = ref("director_notes.txt");
const importRoleIdsCsv = ref("director");
const importContentText = ref("动作分解要求：先建立冲突，再给动作节奏，再输出安全边界。");
const importJobs = ref<KnowledgeImportJobResponse[]>([]);

const message = ref("");
const errorMessage = ref("");

const roleSelectOptions = computed(() =>
  roleProfiles.value.map((item) => ({ label: item.role_id, value: item.role_id }))
);

const skillSelectOptions = computed(() =>
  skillRegistryItems.value.map((item) => ({ label: item.skill_id, value: item.skill_id }))
);

const knowledgePackColumns: DataTableColumns<KnowledgePackItemResponse> = [
  { title: "Pack", key: "pack_name" },
  { title: "Role", key: "role_id" },
  { title: "Collection", key: "collection_id" },
  { title: "KB Version", key: "kb_version_id" },
  { title: "Docs", key: "created_documents" },
];

const importJobColumns: DataTableColumns<KnowledgeImportJobResponse> = [
  { title: "Job", key: "import_job_id" },
  { title: "Source", key: "source_name" },
  { title: "Format", key: "source_format" },
  { title: "Created", key: "created_documents" },
  { title: "Dedup", key: "deduplicated_documents" },
];

const sourceFormatOptions = [
  { label: "txt", value: "txt" },
  { label: "pdf", value: "pdf" },
  { label: "excel/csv", value: "excel" },
  { label: "markdown", value: "markdown" },
];

function clearNotice(): void {
  message.value = "";
  errorMessage.value = "";
}

function stringifyError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function parseObject(text: string): Record<string, unknown> {
  const parsed = JSON.parse(text) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("json must be object");
  }
  return parsed as Record<string, unknown>;
}

function parseCsv(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

function toPrettyJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

async function onReloadRuntimeData(): Promise<void> {
  clearNotice();
  try {
    const [roles, skills, packs, jobs] = await Promise.all([
      listRoleProfiles({ tenant_id: tenantId.value, project_id: projectId.value, keyword: keyword.value || undefined }),
      listSkillRegistry({ tenant_id: tenantId.value, project_id: projectId.value, keyword: keyword.value || undefined }),
      listKnowledgePacks({ tenant_id: tenantId.value, project_id: projectId.value }),
      listKnowledgeImportJobs({ tenant_id: tenantId.value, project_id: projectId.value }),
    ]);
    roleProfiles.value = roles;
    skillRegistryItems.value = skills;
    knowledgePacks.value = packs;
    importJobs.value = jobs;
    if (!resolveRoleId.value && roles.length > 0) {
      resolveRoleId.value = roles[0].role_id;
    }
    if (!resolveSkillId.value && skills.length > 0) {
      resolveSkillId.value = skills[0].skill_id;
    }
    message.value = "工作台数据已刷新";
  } catch (error) {
    errorMessage.value = `reload failed: ${stringifyError(error)}`;
  }
}

async function onResolveRuntime(): Promise<void> {
  clearNotice();
  if (!resolveRoleId.value || !resolveSkillId.value) {
    errorMessage.value = "select role and skill first";
    return;
  }
  try {
    const response = await resolveRoleStudioRuntime({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      role_id: resolveRoleId.value,
      skill_id: resolveSkillId.value,
      context: {},
    });
    resolveText.value = toPrettyJson(response);
    message.value = "runtime resolved";
  } catch (error) {
    errorMessage.value = `resolve runtime failed: ${stringifyError(error)}`;
  }
}

async function onRunSkill(): Promise<void> {
  clearNotice();
  if (!resolveRoleId.value || !resolveSkillId.value) {
    errorMessage.value = "select role and skill first";
    return;
  }
  try {
    const response = await runRoleStudioSkill({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      role_id: resolveRoleId.value,
      skill_id: resolveSkillId.value,
      input_payload: parseObject(runInputText.value),
      context: parseObject(runContextText.value),
    });
    runExecutionSummary.value = `mode=${response.execution_mode} status=${response.status} run=${response.run_id}`;
    runResultText.value = toPrettyJson(response.output || {});
    runLogText.value = toPrettyJson(response.logs || []);
    message.value = "skill executed";
  } catch (error) {
    errorMessage.value = `run skill failed: ${stringifyError(error)}`;
  }
}

async function onBootstrapKnowledgePack(): Promise<void> {
  clearNotice();
  try {
    await bootstrapKnowledgePack({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      role_id: bootstrapRoleId.value,
      pack_name: bootstrapPackName.value || undefined,
      template_key: bootstrapTemplateKey.value || undefined,
      language_code: bootstrapLanguageCode.value || undefined,
      default_knowledge_scope: bootstrapScope.value || undefined,
    });
    knowledgePacks.value = await listKnowledgePacks({
      tenant_id: tenantId.value,
      project_id: projectId.value,
    });
    message.value = "knowledge pack bootstrapped";
  } catch (error) {
    errorMessage.value = `bootstrap knowledge pack failed: ${stringifyError(error)}`;
  }
}

async function onCreateImportJob(): Promise<void> {
  clearNotice();
  try {
    await createKnowledgeImportJob({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      collection_id: importCollectionId.value,
      kb_version_id: importKbVersionId.value || undefined,
      source_format: importSourceFormat.value,
      source_name: importSourceName.value,
      content_text: importContentText.value,
      role_ids: parseCsv(importRoleIdsCsv.value),
      language_code: bootstrapLanguageCode.value || undefined,
      scope: bootstrapScope.value || undefined,
    });
    importJobs.value = await listKnowledgeImportJobs({
      tenant_id: tenantId.value,
      project_id: projectId.value,
    });
    message.value = "import job created";
  } catch (error) {
    errorMessage.value = `create import job failed: ${stringifyError(error)}`;
  }
}

onMounted(() => {
  void onReloadRuntimeData();
});
</script>
