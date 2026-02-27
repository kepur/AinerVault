<template>
  <div class="page-grid">
    <NCard title="Role Config Center">
      <NGrid :cols="3" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Tenant ID"><NInput v-model:value="tenantId" /></NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Project ID"><NInput v-model:value="projectId" /></NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Keyword"><NInput v-model:value="keyword" placeholder="filter" /></NFormItem>
        </NGridItem>
      </NGrid>
      <NSpace>
        <NButton type="primary" @click="onReloadAll">刷新全部</NButton>
      </NSpace>
    </NCard>

    <NGrid :cols="2" :x-gap="12" :y-gap="12" responsive="screen" item-responsive>
      <NGridItem span="0:2 1200:1">
        <NCard title="Role Profiles">
          <NGrid :cols="2" :x-gap="8" :y-gap="8" responsive="screen" item-responsive>
            <NGridItem span="0:2 900:1"><NFormItem label="Role ID"><NInput v-model:value="roleId" /></NFormItem></NGridItem>
            <NGridItem span="0:2 900:1"><NFormItem label="Default Model Profile"><NSelect v-model:value="roleDefaultModelProfile" :options="modelProfileOptions" clearable filterable /></NFormItem></NGridItem>
          </NGrid>
          <NFormItem label="Prompt Style"><NInput v-model:value="rolePromptStyle" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" /></NFormItem>
          <NFormItem label="Default Skills CSV"><NInput v-model:value="roleDefaultSkillsCsv" placeholder="shot_planner,translator_zh_en" /></NFormItem>
          <NFormItem label="Default Knowledge Scopes CSV"><NInput v-model:value="roleKnowledgeScopesCsv" placeholder="director_basic,project_novel" /></NFormItem>
          <NGrid :cols="4" :x-gap="8" :y-gap="8" responsive="screen" item-responsive>
            <NGridItem span="0:4 900:1"><NFormItem label="Import"><NSwitch v-model:value="permImport" /></NFormItem></NGridItem>
            <NGridItem span="0:4 900:1"><NFormItem label="Publish"><NSwitch v-model:value="permPublish" /></NFormItem></NGridItem>
            <NGridItem span="0:4 900:1"><NFormItem label="Global KB"><NSwitch v-model:value="permEditGlobalKb" /></NFormItem></NGridItem>
            <NGridItem span="0:4 900:1"><NFormItem label="Model Router"><NSwitch v-model:value="permManageRouter" /></NFormItem></NGridItem>
          </NGrid>
          <NSpace>
            <NButton type="primary" @click="onUpsertRole">保存 Role</NButton>
            <NButton type="error" :disabled="!roleId" @click="onDeleteRole(roleId)">删除 Role</NButton>
          </NSpace>
          <NDataTable :columns="roleColumns" :data="roleProfiles" :pagination="{ pageSize: 6 }" />
        </NCard>
      </NGridItem>

      <NGridItem span="0:2 1200:1">
        <NCard title="Skill Registry">
          <NGrid :cols="2" :x-gap="8" :y-gap="8" responsive="screen" item-responsive>
            <NGridItem span="0:2 900:1"><NFormItem label="Skill ID"><NInput v-model:value="skillId" /></NFormItem></NGridItem>
            <NGridItem span="0:2 900:1"><NFormItem label="UI Renderer"><NInput v-model:value="skillUiRenderer" placeholder="form/table/timeline" /></NFormItem></NGridItem>
            <NGridItem span="0:2 900:1"><NFormItem label="Default Model Profile"><NSelect v-model:value="skillDefaultModelProfile" :options="modelProfileOptions" clearable filterable /></NFormItem></NGridItem>
            <NGridItem span="0:2 900:1"><NFormItem label="Tools CSV"><NInput v-model:value="skillToolsCsv" placeholder="embedding,search,tts" /></NFormItem></NGridItem>
          </NGrid>
          <NFormItem label="Required Knowledge Scopes CSV"><NInput v-model:value="skillKnowledgeScopesCsv" /></NFormItem>
          <NFormItem label="Input Schema JSON"><NInput v-model:value="skillInputSchemaText" type="textarea" :autosize="{ minRows: 2, maxRows: 5 }" /></NFormItem>
          <NFormItem label="Output Schema JSON"><NInput v-model:value="skillOutputSchemaText" type="textarea" :autosize="{ minRows: 2, maxRows: 5 }" /></NFormItem>
          <NFormItem label="Init Template"><NInput v-model:value="skillInitTemplate" /></NFormItem>
          <NSpace>
            <NButton type="primary" @click="onUpsertSkill">保存 Skill</NButton>
            <NButton type="error" :disabled="!skillId" @click="onDeleteSkill(skillId)">删除 Skill</NButton>
          </NSpace>
          <NDataTable :columns="skillColumns" :data="skillRegistryItems" :pagination="{ pageSize: 6 }" />
        </NCard>
      </NGridItem>

      <NGridItem span="0:2">
        <NCard title="Feature Route Map">
          <NGrid :cols="2" :x-gap="8" :y-gap="8" responsive="screen" item-responsive>
            <NGridItem span="0:2 900:1"><NFormItem label="Route ID"><NInput v-model:value="routeId" /></NFormItem></NGridItem>
            <NGridItem span="0:2 900:1"><NFormItem label="Path"><NInput v-model:value="routePath" placeholder="/studio/xxx" /></NFormItem></NGridItem>
            <NGridItem span="0:2 900:1"><NFormItem label="Component"><NInput v-model:value="routeComponent" /></NFormItem></NGridItem>
            <NGridItem span="0:2 900:1"><NFormItem label="Feature ID"><NInput v-model:value="routeFeatureId" /></NFormItem></NGridItem>
            <NGridItem span="0:2 900:1"><NFormItem label="UI Mode"><NInput v-model:value="routeUiMode" placeholder="list/edit/timeline/config" /></NFormItem></NGridItem>
            <NGridItem span="0:2 900:1"><NFormItem label="Depends On CSV"><NInput v-model:value="routeDependsOnCsv" placeholder="rag,embedding,minio" /></NFormItem></NGridItem>
          </NGrid>
          <NFormItem label="Allowed Roles CSV"><NInput v-model:value="routeAllowedRolesCsv" placeholder="director,translator" /></NFormItem>
          <NSpace>
            <NButton type="primary" @click="onUpsertRoute">保存 Route</NButton>
            <NButton type="error" :disabled="!routeId" @click="onDeleteRoute(routeId)">删除 Route</NButton>
          </NSpace>
          <NDataTable :columns="routeColumns" :data="featureRoutes" :pagination="{ pageSize: 6 }" />
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
  NSwitch,
  type DataTableColumns,
} from "naive-ui";

import {
  deleteFeatureRouteMap,
  deleteRoleProfile,
  deleteSkillRegistry,
  listFeatureRouteMaps,
  listModelProfiles,
  listRoleProfiles,
  listSkillRegistry,
  upsertFeatureRouteMap,
  upsertRoleProfile,
  upsertSkillRegistry,
  type FeatureRouteMapResponse,
  type ModelProfileResponse,
  type RoleProfileResponse,
  type SkillRegistryResponse,
} from "@/api/product";

const tenantId = ref("default");
const projectId = ref("default");
const keyword = ref("");

const modelProfiles = ref<ModelProfileResponse[]>([]);
const roleProfiles = ref<RoleProfileResponse[]>([]);
const skillRegistryItems = ref<SkillRegistryResponse[]>([]);
const featureRoutes = ref<FeatureRouteMapResponse[]>([]);

const roleId = ref("director");
const rolePromptStyle = ref("cinematic, decisive, output structured checklist");
const roleDefaultSkillsCsv = ref("shot_planner,dialogue_director,review_gate");
const roleKnowledgeScopesCsv = ref("director_basic,project_style");
const roleDefaultModelProfile = ref<string | null>(null);
const permImport = ref(true);
const permPublish = ref(true);
const permEditGlobalKb = ref(false);
const permManageRouter = ref(false);

const skillId = ref("shot_planner");
const skillUiRenderer = ref("timeline");
const skillDefaultModelProfile = ref<string | null>(null);
const skillToolsCsv = ref("search,embedding");
const skillKnowledgeScopesCsv = ref("director_basic,visual_grammar");
const skillInputSchemaText = ref('{"type":"object","properties":{"chapter_id":{"type":"string"}}}');
const skillOutputSchemaText = ref('{"type":"object","properties":{"shot_plan":{"type":"array"}}}');
const skillInitTemplate = ref("director_bootstrap_v1");

const routeId = ref("route_scene_board");
const routePath = ref("/studio/scene-board");
const routeComponent = ref("StudioSceneBoardPage");
const routeFeatureId = ref("shot_planner");
const routeUiMode = ref("timeline");
const routeAllowedRolesCsv = ref("director,script_supervisor");
const routeDependsOnCsv = ref("rag,embedding,minio");

const message = ref("");
const errorMessage = ref("");

const modelProfileOptions = computed(() =>
  modelProfiles.value.map((item) => ({
    label: `${item.purpose} · ${item.name} (${item.id})`,
    value: item.id,
  }))
);

const roleColumns: DataTableColumns<RoleProfileResponse> = [
  { title: "Role", key: "role_id" },
  { title: "Default Model", key: "default_model_profile" },
  { title: "Skills", key: "default_skills", render: (row) => row.default_skills.join(",") },
  {
    title: "Action",
    key: "action",
    render: (row) =>
      h(NSpace, { size: 6 }, {
        default: () => [
          h(NButton, { size: "tiny", onClick: () => useRole(row) }, { default: () => "Use" }),
          h(NButton, { size: "tiny", type: "error", onClick: () => void onDeleteRole(row.role_id) }, { default: () => "Delete" }),
        ],
      }),
  },
];

const skillColumns: DataTableColumns<SkillRegistryResponse> = [
  { title: "Skill", key: "skill_id" },
  { title: "Renderer", key: "ui_renderer" },
  { title: "Default Model", key: "default_model_profile" },
  {
    title: "Action",
    key: "action",
    render: (row) =>
      h(NSpace, { size: 6 }, {
        default: () => [
          h(NButton, { size: "tiny", onClick: () => useSkill(row) }, { default: () => "Use" }),
          h(NButton, { size: "tiny", type: "error", onClick: () => void onDeleteSkill(row.skill_id) }, { default: () => "Delete" }),
        ],
      }),
  },
];

const routeColumns: DataTableColumns<FeatureRouteMapResponse> = [
  { title: "Route", key: "route_id" },
  { title: "Path", key: "path" },
  { title: "Feature", key: "feature_id" },
  { title: "Roles", key: "allowed_roles", render: (row) => row.allowed_roles.join(",") },
  {
    title: "Action",
    key: "action",
    render: (row) =>
      h(NSpace, { size: 6 }, {
        default: () => [
          h(NButton, { size: "tiny", onClick: () => useRoute(row) }, { default: () => "Use" }),
          h(NButton, { size: "tiny", type: "error", onClick: () => void onDeleteRoute(row.route_id) }, { default: () => "Delete" }),
        ],
      }),
  },
];

function stringifyError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function parseCsv(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

function parseObject(text: string): Record<string, unknown> {
  const parsed = JSON.parse(text) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("json must be object");
  }
  return parsed as Record<string, unknown>;
}

function clearNotice(): void {
  message.value = "";
  errorMessage.value = "";
}

function useRole(row: RoleProfileResponse): void {
  roleId.value = row.role_id;
  rolePromptStyle.value = row.prompt_style;
  roleDefaultSkillsCsv.value = row.default_skills.join(",");
  roleKnowledgeScopesCsv.value = row.default_knowledge_scopes.join(",");
  roleDefaultModelProfile.value = row.default_model_profile || null;
  permImport.value = row.permissions.can_import_data;
  permPublish.value = row.permissions.can_publish_task;
  permEditGlobalKb.value = row.permissions.can_edit_global_knowledge;
  permManageRouter.value = row.permissions.can_manage_model_router;
}

function useSkill(row: SkillRegistryResponse): void {
  skillId.value = row.skill_id;
  skillUiRenderer.value = row.ui_renderer;
  skillDefaultModelProfile.value = row.default_model_profile || null;
  skillToolsCsv.value = row.tools_required.join(",");
  skillKnowledgeScopesCsv.value = row.required_knowledge_scopes.join(",");
  skillInputSchemaText.value = JSON.stringify(row.input_schema || {}, null, 2);
  skillOutputSchemaText.value = JSON.stringify(row.output_schema || {}, null, 2);
  skillInitTemplate.value = row.init_template || "";
}

function useRoute(row: FeatureRouteMapResponse): void {
  routeId.value = row.route_id;
  routePath.value = row.path;
  routeComponent.value = row.component;
  routeFeatureId.value = row.feature_id;
  routeUiMode.value = row.ui_mode;
  routeAllowedRolesCsv.value = row.allowed_roles.join(",");
  routeDependsOnCsv.value = row.depends_on.join(",");
}

async function onReloadAll(): Promise<void> {
  clearNotice();
  try {
    const [profiles, roles, skills, routes] = await Promise.all([
      listModelProfiles({ tenant_id: tenantId.value, project_id: projectId.value }),
      listRoleProfiles({ tenant_id: tenantId.value, project_id: projectId.value, keyword: keyword.value || undefined }),
      listSkillRegistry({ tenant_id: tenantId.value, project_id: projectId.value, keyword: keyword.value || undefined }),
      listFeatureRouteMaps({ tenant_id: tenantId.value, project_id: projectId.value, keyword: keyword.value || undefined }),
    ]);
    modelProfiles.value = profiles;
    roleProfiles.value = roles;
    skillRegistryItems.value = skills;
    featureRoutes.value = routes;
    message.value = "配置已刷新";
  } catch (error) {
    errorMessage.value = `reload failed: ${stringifyError(error)}`;
  }
}

async function onUpsertRole(): Promise<void> {
  clearNotice();
  try {
    await upsertRoleProfile(roleId.value, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      role_id: roleId.value,
      prompt_style: rolePromptStyle.value,
      default_skills: parseCsv(roleDefaultSkillsCsv.value),
      default_knowledge_scopes: parseCsv(roleKnowledgeScopesCsv.value),
      default_model_profile: roleDefaultModelProfile.value || undefined,
      permissions: {
        can_import_data: permImport.value,
        can_publish_task: permPublish.value,
        can_edit_global_knowledge: permEditGlobalKb.value,
        can_manage_model_router: permManageRouter.value,
      },
      enabled: true,
      schema_version: "1.0",
    });
    await onReloadAll();
    message.value = `role upserted: ${roleId.value}`;
  } catch (error) {
    errorMessage.value = `upsert role failed: ${stringifyError(error)}`;
  }
}

async function onDeleteRole(targetRoleId: string): Promise<void> {
  clearNotice();
  try {
    await deleteRoleProfile(targetRoleId, { tenant_id: tenantId.value, project_id: projectId.value });
    await onReloadAll();
    message.value = `role deleted: ${targetRoleId}`;
  } catch (error) {
    errorMessage.value = `delete role failed: ${stringifyError(error)}`;
  }
}

async function onUpsertSkill(): Promise<void> {
  clearNotice();
  try {
    await upsertSkillRegistry(skillId.value, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      skill_id: skillId.value,
      input_schema: parseObject(skillInputSchemaText.value),
      output_schema: parseObject(skillOutputSchemaText.value),
      required_knowledge_scopes: parseCsv(skillKnowledgeScopesCsv.value),
      default_model_profile: skillDefaultModelProfile.value || undefined,
      tools_required: parseCsv(skillToolsCsv.value),
      ui_renderer: skillUiRenderer.value,
      init_template: skillInitTemplate.value || undefined,
      enabled: true,
      schema_version: "1.0",
    });
    await onReloadAll();
    message.value = `skill upserted: ${skillId.value}`;
  } catch (error) {
    errorMessage.value = `upsert skill failed: ${stringifyError(error)}`;
  }
}

async function onDeleteSkill(targetSkillId: string): Promise<void> {
  clearNotice();
  try {
    await deleteSkillRegistry(targetSkillId, { tenant_id: tenantId.value, project_id: projectId.value });
    await onReloadAll();
    message.value = `skill deleted: ${targetSkillId}`;
  } catch (error) {
    errorMessage.value = `delete skill failed: ${stringifyError(error)}`;
  }
}

async function onUpsertRoute(): Promise<void> {
  clearNotice();
  try {
    await upsertFeatureRouteMap(routeId.value, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      route_id: routeId.value,
      path: routePath.value,
      component: routeComponent.value,
      feature_id: routeFeatureId.value,
      allowed_roles: parseCsv(routeAllowedRolesCsv.value),
      ui_mode: routeUiMode.value,
      depends_on: parseCsv(routeDependsOnCsv.value),
      enabled: true,
      schema_version: "1.0",
    });
    await onReloadAll();
    message.value = `route upserted: ${routeId.value}`;
  } catch (error) {
    errorMessage.value = `upsert route failed: ${stringifyError(error)}`;
  }
}

async function onDeleteRoute(targetRouteId: string): Promise<void> {
  clearNotice();
  try {
    await deleteFeatureRouteMap(targetRouteId, { tenant_id: tenantId.value, project_id: projectId.value });
    await onReloadAll();
    message.value = `route deleted: ${targetRouteId}`;
  } catch (error) {
    errorMessage.value = `delete route failed: ${stringifyError(error)}`;
  }
}

onMounted(() => {
  void onReloadAll();
});
</script>
