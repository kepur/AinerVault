<template>
  <div class="page-grid">
    <NCard :title="t('persona.library')">
      <NGrid :cols="3" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Tenant ID"><NInput v-model:value="tenantId" /></NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Project ID"><NInput v-model:value="projectId" /></NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="关键词过滤"><NInput v-model:value="keyword" placeholder="name keyword" /></NFormItem>
        </NGridItem>
      </NGrid>
      <NSpace>
        <NButton type="primary" @click="onReloadAll">{{ t('common.refresh') }}</NButton>
        <NButton @click="openCreateDrawer">{{ t('persona.create') }}</NButton>
      </NSpace>
    </NCard>

    <NCard :title="t('persona.list')">
      <NDataTable :columns="packColumns" :data="filteredPacks" :pagination="{ pageSize: 10 }" />
    </NCard>

    <NCard :title="t('persona.preview')">
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 900:1">
          <NFormItem label="Persona Pack">
            <NSelect
              v-model:value="previewPackId"
              :options="packOptions"
              placeholder="选择 Pack 后加载版本"
              filterable
              @update:value="onSelectPreviewPack"
            />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 900:1">
          <NFormItem label="Persona 版本">
            <NSelect
              v-model:value="previewVersionId"
              :options="previewVersionOptions"
              placeholder="选择版本"
              filterable
            />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2">
          <NFormItem label="预览查询文本">
            <NInput v-model:value="previewQuery" placeholder="输入测试查询..." />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NButton type="info" :disabled="!previewVersionId" @click="onPreviewPersona">预览 Persona</NButton>
      <pre v-if="previewText" class="json-panel" style="margin-top:12px">{{ previewText }}</pre>
    </NCard>

    <!-- Create / Edit Drawer -->
    <NDrawer v-model:show="drawerVisible" :width="480" placement="right">
      <NDrawerContent :title="editingPack ? '编辑 Persona' : '创建 Persona'" closable>
        <NForm label-placement="top">
          <NFormItem label="Persona 名称">
            <NInput v-model:value="form.name" placeholder="director_A" />
          </NFormItem>
          <NFormItem label="绑定职业 (Role ID)">
            <NSelect
              v-model:value="form.roleId"
              :options="roleOptions"
              placeholder="选择职业"
              filterable
              clearable
            />
          </NFormItem>
          <NFormItem label="风格模板">
            <NSelect v-model:value="form.styleTemplate" :options="styleTemplateOptions" />
          </NFormItem>
          <NFormItem label="语言偏好">
            <NSelect v-model:value="form.language" :options="languageOptions" />
          </NFormItem>
          <NFormItem label="高级模式">
            <NSwitch v-model:value="form.advancedMode" />
          </NFormItem>
          <template v-if="form.advancedMode">
            <NFormItem label="style_json（原始 JSON）">
              <NInput v-model:value="form.styleJson" type="textarea" :autosize="{ minRows: 4, maxRows: 10 }" />
            </NFormItem>
          </template>
        </NForm>
        <NSpace style="margin-top:16px">
          <NButton type="primary" :loading="isSaving" @click="onSavePersona">{{ t('common.save') }}</NButton>
          <NButton @click="drawerVisible = false">{{ t('common.cancel') }}</NButton>
        </NSpace>
      </NDrawerContent>
    </NDrawer>

    <!-- Version drawer -->
    <NDrawer v-model:show="versionDrawerVisible" :width="440" placement="right">
      <NDrawerContent title="Persona 版本" closable>
        <NText depth="3">Pack: {{ selectedPackName }}</NText>
        <NDivider />
        <NFormItem label="版本名称">
          <NInput v-model:value="newVersionName" placeholder="v1" />
        </NFormItem>
        <NButton type="primary" @click="onCreateVersion">新增版本</NButton>
        <NDivider />
        <NDataTable :columns="versionColumns" :data="personaVersions" :pagination="{ pageSize: 6 }" />
      </NDrawerContent>
    </NDrawer>

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
  NDrawer,
  NDrawerContent,
  NForm,
  NFormItem,
  NGrid,
  NGridItem,
  NInput,
  NSelect,
  NSpace,
  NSwitch,
  NText,
  type DataTableColumns,
} from "naive-ui";
import { useI18n } from "@/composables/useI18n";


import {
  createPersonaPack,
  createPersonaVersion,
  deletePersonaPack,
  listPersonaPacks,
  listPersonaVersions,
  listRoleProfiles,
  previewPersona,
  type PersonaPackResponse,
  type PersonaVersionResponse,
  type RoleProfileResponse,
} from "@/api/product";

const { t } = useI18n();

const tenantId = ref("default");
const projectId = ref("default");
const keyword = ref("");

const personaPacks = ref<PersonaPackResponse[]>([]);
const personaVersions = ref<PersonaVersionResponse[]>([]);
const roleProfiles = ref<RoleProfileResponse[]>([]);

const selectedPackId = ref("");
const selectedPackName = ref("");

const drawerVisible = ref(false);
const versionDrawerVisible = ref(false);
const editingPack = ref<PersonaPackResponse | null>(null);
const isSaving = ref(false);
const newVersionName = ref("v1");

const previewPackId = ref<string | null>(null);
const previewVersionId = ref<string | null>(null);
const previewVersions = ref<PersonaVersionResponse[]>([]);
const previewQuery = ref("sword tavern scene");
const previewText = ref("");

const message = ref("");
const errorMessage = ref("");

const form = ref({
  name: "director_A",
  roleId: null as string | null,
  styleTemplate: "cinematic",
  language: "zh-CN",
  advancedMode: false,
  styleJson: "{}",
});

const styleTemplateOptions = [
  { label: "cinematic（电影感）", value: "cinematic" },
  { label: "documentary（纪录片）", value: "documentary" },
  { label: "wuxia（武侠）", value: "wuxia" },
  { label: "anime（动漫）", value: "anime" },
  { label: "noir（黑色）", value: "noir" },
  { label: "game（游戏）", value: "game" },
];

const languageOptions = [
  { label: "简体中文 (zh-CN)", value: "zh-CN" },
  { label: "英语 (US/Global) / English", value: "en-US" },
  { label: "日语 (ja-JP) / 日本語", value: "ja-JP" },
  { label: "阿拉伯语 (ar-SA) / العربية", value: "ar-SA" },
  { label: "西语 (es-MX) / Español", value: "es-MX" },
  { label: "越南语 (vi-VN) / Tiếng Việt", value: "vi-VN" },
  { label: "葡萄牙语 (pt-BR) / Português", value: "pt-BR" },
  { label: "印地语 (hi-IN) / हिन्दी", value: "hi-IN" },
  { label: "德语 (de-DE) / Deutsch", value: "de-DE" },
  { label: "菲律宾语 (tl-PH) / Filipino", value: "tl-PH" },
];

const filteredPacks = computed(() => {
  const q = keyword.value.trim().toLowerCase();
  if (!q) return personaPacks.value;
  return personaPacks.value.filter(p => p.name.toLowerCase().includes(q));
});

const packOptions = computed(() =>
  personaPacks.value.map(p => ({ label: p.name, value: p.id }))
);

const previewVersionOptions = computed(() =>
  previewVersions.value.map(v => ({ label: v.version_name, value: v.id }))
);

const roleOptions = computed(() =>
  roleProfiles.value.map(r => ({ label: r.role_id, value: r.role_id }))
);

const packColumns: DataTableColumns<PersonaPackResponse> = [
  { title: "名称", key: "name" },
  { title: "ID", key: "id", ellipsis: true },
  {
    title: "操作",
    key: "action",
    width: 200,
    render: (row) =>
      h(NSpace, { size: 6 }, {
        default: () => [
          h(NButton, {
            size: "tiny",
            onClick: () => openVersionDrawer(row),
          }, { default: () => "版本" }),
          h(NButton, {
            size: "tiny",
            onClick: () => openEditDrawer(row),
          }, { default: () => "编辑" }),
          h(NButton, {
            size: "tiny",
            type: "error",
            onClick: () => void onDeletePack(row.id),
          }, { default: () => "删除" }),
        ],
      }),
  },
];

const versionColumns: DataTableColumns<PersonaVersionResponse> = [
  { title: "版本", key: "version_name" },
  { title: "ID", key: "id", ellipsis: true },
];

function stringifyError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function clearNotice(): void {
  message.value = "";
  errorMessage.value = "";
}

function openCreateDrawer(): void {
  editingPack.value = null;
  form.value = { name: "director_A", roleId: null, styleTemplate: "cinematic", language: "zh-CN", advancedMode: false, styleJson: "{}" };
  drawerVisible.value = true;
}

function openEditDrawer(pack: PersonaPackResponse): void {
  editingPack.value = pack;
  form.value = { name: pack.name, roleId: null, styleTemplate: "cinematic", language: "zh-CN", advancedMode: false, styleJson: "{}" };
  drawerVisible.value = true;
}

function openVersionDrawer(pack: PersonaPackResponse): void {
  selectedPackId.value = pack.id;
  selectedPackName.value = pack.name;
  personaVersions.value = [];
  versionDrawerVisible.value = true;
  void onListVersions(pack.id);
}

async function onReloadAll(): Promise<void> {
  clearNotice();
  try {
    const [packs, roles] = await Promise.all([
      listPersonaPacks({ tenant_id: tenantId.value, project_id: projectId.value }),
      listRoleProfiles({ tenant_id: tenantId.value, project_id: projectId.value }),
    ]);
    personaPacks.value = packs;
    roleProfiles.value = roles;
  } catch (error) {
    errorMessage.value = `reload failed: ${stringifyError(error)}`;
  }
}

async function onSavePersona(): Promise<void> {
  clearNotice();
  isSaving.value = true;
  try {
    await createPersonaPack({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      name: form.value.name,
    });
    await onReloadAll();
    drawerVisible.value = false;
    message.value = `Persona 已创建: ${form.value.name}`;
  } catch (error) {
    errorMessage.value = `save failed: ${stringifyError(error)}`;
  } finally {
    isSaving.value = false;
  }
}

async function onDeletePack(packId: string): Promise<void> {
  clearNotice();
  try {
    await deletePersonaPack(packId, { tenant_id: tenantId.value, project_id: projectId.value });
    await onReloadAll();
    message.value = `Persona 已删除`;
  } catch (error) {
    errorMessage.value = `delete failed: ${stringifyError(error)}`;
  }
}

async function onListVersions(packId: string): Promise<void> {
  try {
    personaVersions.value = await listPersonaVersions(packId);
  } catch (error) {
    errorMessage.value = `list versions failed: ${stringifyError(error)}`;
  }
}

async function onCreateVersion(): Promise<void> {
  clearNotice();
  try {
    await createPersonaVersion(selectedPackId.value, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      version_name: newVersionName.value,
    });
    await onListVersions(selectedPackId.value);
    message.value = `版本 ${newVersionName.value} 已创建`;
  } catch (error) {
    errorMessage.value = `create version failed: ${stringifyError(error)}`;
  }
}

async function onSelectPreviewPack(packId: string | null): Promise<void> {
  previewVersionId.value = null;
  previewVersions.value = [];
  if (!packId) return;
  try {
    previewVersions.value = await listPersonaVersions(packId);
  } catch (error) {
    errorMessage.value = `load versions failed: ${stringifyError(error)}`;
  }
}

async function onPreviewPersona(): Promise<void> {
  if (!previewVersionId.value) return;
  clearNotice();
  try {
    const result = await previewPersona({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      persona_pack_version_id: previewVersionId.value,
      query: previewQuery.value,
    });
    previewText.value = JSON.stringify(result, null, 2);
  } catch (error) {
    errorMessage.value = `preview failed: ${stringifyError(error)}`;
  }
}

onMounted(() => {
  void onReloadAll();
});
</script>
