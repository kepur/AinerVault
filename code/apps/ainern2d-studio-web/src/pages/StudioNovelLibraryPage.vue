<template>
  <div class="page-grid">
    <NCard title="SKILL 24 · 小说管理（Novel Library）">
      <NGrid :cols="3" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:3 900:1"><NFormItem label="Tenant ID"><NInput v-model:value="tenantId" /></NFormItem></NGridItem>
        <NGridItem span="0:3 900:1"><NFormItem label="Project ID"><NInput v-model:value="projectId" /></NFormItem></NGridItem>
        <NGridItem span="0:3 900:1"><NFormItem label="关键词过滤"><NInput v-model:value="keyword" placeholder="title keyword" /></NFormItem></NGridItem>
      </NGrid>
      <NSpace>
        <NButton @click="onLoadLanguagePolicy">{{ t('common.refresh') }}</NButton>
        <NButton @click="onListNovels">{{ t('common.refresh') }}</NButton>
        <NButton type="primary" @click="showCreate = !showCreate">{{ t('novels.create') }}</NButton>
      </NSpace>
    </NCard>

    <NCard v-if="showCreate" :title="t('novels.create')">
      <NGrid :cols="2" :x-gap="10" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 900:1"><NFormItem label="标题"><NInput v-model:value="title" /></NFormItem></NGridItem>
        <NGridItem span="0:2 900:1"><NFormItem label="默认语言"><NSelect v-model:value="defaultLanguage" :options="languageOptions" filterable /></NFormItem></NGridItem>
      </NGrid>
      <NFormItem label="摘要"><NInput v-model:value="summary" type="textarea" :autosize="{ minRows: 3, maxRows: 6 }" /></NFormItem>
      <NSpace>
        <NButton type="primary" @click="onCreateNovel">{{ t('common.create') }}</NButton>
        <NButton @click="showCreate = false">{{ t('common.cancel') }}</NButton>
      </NSpace>
    </NCard>

    <NCard :title="t('novels.title')">
      <NDataTable :columns="columns" :data="filteredNovels" :pagination="{ pageSize: 10 }" />
    </NCard>

    <!-- Edit Drawer -->
    <NDrawer v-model:show="editDrawerVisible" :width="440" placement="right">
      <NDrawerContent :title="t('novels.edit')" closable>
        <NForm label-placement="top">
          <NFormItem label="标题">
            <NInput v-model:value="editTitle" />
          </NFormItem>
          <NFormItem label="默认语言">
            <NSelect v-model:value="editLanguage" :options="languageOptions" />
          </NFormItem>
          <NFormItem label="摘要">
            <NInput v-model:value="editSummary" type="textarea" :autosize="{ minRows: 3, maxRows: 6 }" />
          </NFormItem>
        </NForm>
        <NSpace style="margin-top:16px">
          <NButton type="primary" @click="onUpdateNovel">{{ t('common.save') }}</NButton>
          <NButton @click="editDrawerVisible = false">{{ t('common.cancel') }}</NButton>
        </NSpace>
      </NDrawerContent>
    </NDrawer>

    <NAlert v-if="message" type="success" :show-icon="true">{{ message }}</NAlert>
    <NAlert v-if="errorMessage" type="error" :show-icon="true">{{ errorMessage }}</NAlert>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import {
  NAlert,
  NButton,
  NCard,
  NDataTable,
  NDrawer,
  NDrawerContent,
  NForm,
  NFormItem,
  NGrid,
  NGridItem,
  NInput,
  NPopconfirm,
  NSelect,
  NSpace,
  type DataTableColumns,
} from "naive-ui";
import { useI18n } from "@/composables/useI18n";


import { createNovel, deleteNovel, getLanguageSettings, listNovels, updateNovel, type NovelResponse } from "@/api/product";

const STORAGE_KEY = "studio_selected_novel_id";

interface SelectOption {
  label: string;
  value: string;
}

const { t } = useI18n();

const router = useRouter();
const tenantId = ref("default");
const projectId = ref("default");
const keyword = ref("");
const showCreate = ref(false);
const title = ref("demo novel");
const summary = ref("novel summary");
const defaultLanguage = ref("zh-CN");
const languageOptions = ref<SelectOption[]>([
  { label: "简体中文 (zh-CN)", value: "zh-CN" },
  { label: "English (en-US)", value: "en-US" },
  { label: "日本語 (ja-JP)", value: "ja-JP" },
]);

const novels = ref<NovelResponse[]>([]);
const message = ref("");
const errorMessage = ref("");

// Edit drawer state
const editDrawerVisible = ref(false);
const editingNovel = ref<NovelResponse | null>(null);
const editTitle = ref("");
const editSummary = ref("");
const editLanguage = ref("zh-CN");

const filteredNovels = computed(() => {
  const q = keyword.value.trim().toLowerCase();
  if (!q) {
    return novels.value;
  }
  return novels.value.filter((item) => item.title.toLowerCase().includes(q));
});

const columns: DataTableColumns<NovelResponse> = [
  { title: "标题", key: "title" },
  { title: "默认语言", key: "default_language_code", width: 130 },
  {
    title: "操作",
    key: "action",
    width: 300,
    render: (row) =>
      h(NSpace, { size: 6 }, {
        default: () => [
          h(NButton, {
            size: "small",
            type: "info",
            onClick: () => openDetail(row.id),
          }, { default: () => "进入工作台" }),
          h(NButton, {
            size: "small",
            onClick: () => openEditDrawer(row),
          }, { default: () => "编辑" }),
          h(NPopconfirm, {
            onPositiveClick: () => void onDeleteNovel(row.id),
          }, {
            trigger: () => h(NButton, { size: "small", type: "error" }, { default: () => "删除" }),
            default: () => "确认删除该小说？此操作不可恢复。",
          }),
        ],
      }),
  },
];

function clearNotice(): void {
  message.value = "";
  errorMessage.value = "";
}

function stringifyError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function openDetail(novelId: string): void {
  void router.push({ name: "studio-novel-detail", params: { novelId } });
}

function openEditDrawer(novel: NovelResponse): void {
  editingNovel.value = novel;
  editTitle.value = novel.title;
  editSummary.value = novel.summary ?? "";
  editLanguage.value = novel.default_language_code;
  editDrawerVisible.value = true;
}

async function onLoadLanguagePolicy(): Promise<void> {
  clearNotice();
  try {
    const settings = await getLanguageSettings(tenantId.value, projectId.value);
    const options = settings.enabled_languages
      .filter((item) => item.enabled)
      .map((item) => ({ label: `${item.label} (${item.language_code})`, value: item.language_code }));
    if (options.length > 0) {
      languageOptions.value = options;
    }
    defaultLanguage.value = settings.default_source_language || defaultLanguage.value;
  } catch (error) {
    errorMessage.value = `load language settings failed: ${stringifyError(error)}`;
  }
}

async function onListNovels(): Promise<void> {
  clearNotice();
  try {
    novels.value = await listNovels(tenantId.value, projectId.value);
  } catch (error) {
    errorMessage.value = `list novels failed: ${stringifyError(error)}`;
  }
}

async function onCreateNovel(): Promise<void> {
  clearNotice();
  try {
    const created = await createNovel({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      title: title.value,
      summary: summary.value,
      default_language_code: defaultLanguage.value,
    });
    await onListNovels();
    showCreate.value = false;
    message.value = `novel created: ${created.id}`;
    openDetail(created.id);
  } catch (error) {
    errorMessage.value = `create novel failed: ${stringifyError(error)}`;
  }
}

async function onUpdateNovel(): Promise<void> {
  if (!editingNovel.value) return;
  clearNotice();
  try {
    await updateNovel(editingNovel.value.id, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      title: editTitle.value,
      summary: editSummary.value,
      default_language_code: editLanguage.value,
    });
    await onListNovels();
    editDrawerVisible.value = false;
    message.value = `novel updated: ${editTitle.value}`;
  } catch (error) {
    errorMessage.value = `update novel failed: ${stringifyError(error)}`;
  }
}

async function onDeleteNovel(novelId: string): Promise<void> {
  clearNotice();
  try {
    await deleteNovel(novelId, { tenant_id: tenantId.value, project_id: projectId.value });
    await onListNovels();
    message.value = "novel deleted";
  } catch (error) {
    errorMessage.value = `delete novel failed: ${stringifyError(error)}`;
  }
}

onMounted(() => {
  void onLoadLanguagePolicy();
  void onListNovels();
});
</script>
