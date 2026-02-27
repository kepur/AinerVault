<template>
  <div class="page-grid">
    <NCard title="SKILL 24 · 小说管理（Novel Library）">
      <NGrid :cols="3" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:3 900:1"><NFormItem label="Tenant ID"><NInput v-model:value="tenantId" /></NFormItem></NGridItem>
        <NGridItem span="0:3 900:1"><NFormItem label="Project ID"><NInput v-model:value="projectId" /></NFormItem></NGridItem>
        <NGridItem span="0:3 900:1"><NFormItem label="关键词过滤"><NInput v-model:value="keyword" placeholder="title keyword" /></NFormItem></NGridItem>
      </NGrid>
      <NSpace>
        <NButton @click="onLoadLanguagePolicy">加载语言策略</NButton>
        <NButton @click="onListNovels">刷新小说列表</NButton>
        <NButton type="primary" @click="showCreate = !showCreate">新建小说</NButton>
      </NSpace>
    </NCard>

    <NCard v-if="showCreate" title="新建小说">
      <NGrid :cols="2" :x-gap="10" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 900:1"><NFormItem label="标题"><NInput v-model:value="title" /></NFormItem></NGridItem>
        <NGridItem span="0:2 900:1"><NFormItem label="默认语言"><NSelect v-model:value="defaultLanguage" :options="languageOptions" filterable /></NFormItem></NGridItem>
      </NGrid>
      <NFormItem label="摘要"><NInput v-model:value="summary" type="textarea" :autosize="{ minRows: 3, maxRows: 6 }" /></NFormItem>
      <NSpace>
        <NButton type="primary" @click="onCreateNovel">创建</NButton>
        <NButton @click="showCreate = false">取消</NButton>
      </NSpace>
    </NCard>

    <NCard title="小说列表">
      <NDataTable :columns="columns" :data="filteredNovels" :pagination="{ pageSize: 10 }" />
    </NCard>

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
  NFormItem,
  NGrid,
  NGridItem,
  NInput,
  NSelect,
  NSpace,
  type DataTableColumns,
} from "naive-ui";

import { createNovel, getLanguageSettings, listNovels, type NovelResponse } from "@/api/product";

const STORAGE_KEY = "studio_selected_novel_id";

interface SelectOption {
  label: string;
  value: string;
}

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
    width: 170,
    render: (row) =>
      h(NSpace, { size: 6 }, {
        default: () => [
          h(NButton, {
            size: "small",
            type: "primary",
            onClick: () => openWorkspace(row.id),
          }, { default: () => "打开章节工作区" }),
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

function openWorkspace(novelId: string): void {
  localStorage.setItem(STORAGE_KEY, novelId);
  void router.push({
    name: "studio-chapter-workspace",
    query: { novelId },
  });
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
    openWorkspace(created.id);
  } catch (error) {
    errorMessage.value = `create novel failed: ${stringifyError(error)}`;
  }
}

onMounted(() => {
  void onLoadLanguagePolicy();
  void onListNovels();
});
</script>
