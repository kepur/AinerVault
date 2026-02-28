<template>
  <div class="page-grid">
    <NCard title="SKILL 29 · Asset Library">
      <NGrid :cols="4" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:4 900:1">
          <NFormItem label="Tenant ID">
            <NInput v-model:value="tenantId" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:4 900:1">
          <NFormItem label="Project ID">
            <NInput v-model:value="projectId" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:4 900:1">
          <NFormItem label="小说过滤">
            <NSelect
              v-model:value="filterNovelId"
              :options="novelOptions"
              placeholder="按小说过滤"
              clearable
              filterable
              @update:value="onNovelFilterChange"
            />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:4 900:1">
          <NFormItem label="章节过滤">
            <NSelect
              v-model:value="filterChapterId"
              :options="chapterOptions"
              placeholder="按章节过滤（可选）"
              clearable
              filterable
              :disabled="!filterNovelId"
            />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:4 900:1">
          <NFormItem label="Run ID">
            <NInput v-model:value="runId" placeholder="optional" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:4 900:1">
          <NFormItem label="Shot ID">
            <NInput v-model:value="shotId" placeholder="optional" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NGrid :cols="3" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Asset Type">
            <NInput v-model:value="assetType" placeholder="shot_video / ... " />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Keyword">
            <NInput v-model:value="keyword" placeholder="id / uri / type" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Anchored Filter">
            <NSelect v-model:value="anchoredFilter" :options="anchoredOptions" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NSpace>
        <NButton type="primary" @click="onListAssets">查询素材</NButton>
        <NButton @click="onListAnchors">查询 Anchor</NButton>
      </NSpace>
    </NCard>

    <NCard title="Assets 列表（可删/可锚点）">
      <NDataTable :columns="assetColumns" :data="assets" :pagination="{ pageSize: 10 }" />
    </NCard>

    <NCard title="Anchor Editor">
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 900:1">
          <NFormItem label="Asset ID">
            <NInput v-model:value="assetId" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 900:1">
          <NFormItem label="Entity ID (optional)">
            <NInput v-model:value="entityId" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NFormItem label="Anchor Name">
        <NInput v-model:value="anchorName" />
      </NFormItem>
      <NFormItem label="Anchor Notes">
        <NInput v-model:value="anchorNotes" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" />
      </NFormItem>
      <NSpace>
        <NButton type="primary" @click="onAnchorAsset">设置 Anchor</NButton>
      </NSpace>
      <pre class="json-panel">{{ anchorsText }}</pre>
    </NCard>

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
import { useI18n } from "@/composables/useI18n";



import {
  type ChapterResponse,
  type NovelResponse,
  type ProjectAssetItem,
  deleteAsset,
  listChapters,
  listNovels,
  listProjectAnchors,
  listProjectAssets,
  markAssetAnchor,
} from "@/api/product";

const { t } = useI18n();

const tenantId = ref("default");
const projectId = ref("default");
const runId = ref("");
const shotId = ref("");
const assetType = ref("");
const keyword = ref("");
const anchoredFilter = ref("all");

// Novel/chapter filter
const novels = ref<NovelResponse[]>([]);
const filterChapters = ref<ChapterResponse[]>([]);
const filterNovelId = ref<string | null>(null);
const filterChapterId = ref<string | null>(null);

const novelOptions = computed(() =>
  novels.value.map(n => ({ label: n.title, value: n.id }))
);
const chapterOptions = computed(() =>
  filterChapters.value.map(c => ({ label: `Ch.${c.chapter_no} ${c.title ?? ""}`, value: c.id }))
);

const assets = ref<ProjectAssetItem[]>([]);
const assetId = ref("");
const entityId = ref("");
const anchorName = ref("hero-reference");
const anchorNotes = ref("keep continuity");
const anchorsText = ref("[]");

const message = ref("");
const errorMessage = ref("");

const anchoredOptions = [
  { label: "全部", value: "all" },
  { label: "仅 Anchored", value: "yes" },
  { label: "仅未 Anchored", value: "no" },
];

const assetColumns: DataTableColumns<ProjectAssetItem> = [
  { title: "ID", key: "id" },
  { title: "Type", key: "type" },
  { title: "Run", key: "run_id" },
  { title: "Shot", key: "shot_id" },
  {
    title: "URI",
    key: "uri",
    render: (row) => h("span", { style: "font-size:12px;" }, row.uri),
  },
  {
    title: "Anchored",
    key: "anchored",
    render: (row) => (row.anchored ? "yes" : "no"),
  },
  {
    title: "Action",
    key: "action",
    render: (row) =>
      h(NSpace, { size: 6 }, {
        default: () => [
          h(NButton, { size: "tiny", onClick: () => {
            assetId.value = row.id;
          } }, { default: () => "Anchor" }),
          h(NButton, { size: "tiny", type: "error", onClick: () => void onDeleteAsset(row.id) }, { default: () => "Delete" }),
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

async function onNovelFilterChange(novelId: string | null): Promise<void> {
  filterChapterId.value = null;
  filterChapters.value = [];
  if (!novelId) return;
  try {
    filterChapters.value = await listChapters(novelId);
  } catch {
    // non-critical
  }
}

async function onListAssets(): Promise<void> {
  clearNotice();
  try {
    const anchored =
      anchoredFilter.value === "all" ? undefined : anchoredFilter.value === "yes";
    assets.value = await listProjectAssets({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      chapter_id: filterChapterId.value || undefined,
      run_id: runId.value || undefined,
      shot_id: shotId.value || undefined,
      asset_type: assetType.value || undefined,
      keyword: keyword.value || undefined,
      anchored,
    });
  } catch (error) {
    errorMessage.value = `list assets failed: ${stringifyError(error)}`;
  }
}

async function onDeleteAsset(selectedAssetId: string): Promise<void> {
  clearNotice();
  try {
    await deleteAsset(selectedAssetId, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
    });
    await onListAssets();
    message.value = `asset deleted: ${selectedAssetId}`;
  } catch (error) {
    errorMessage.value = `delete asset failed: ${stringifyError(error)}`;
  }
}

async function onAnchorAsset(): Promise<void> {
  clearNotice();
  if (!assetId.value) {
    errorMessage.value = "asset_id is required";
    return;
  }
  try {
    await markAssetAnchor(assetId.value, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      entity_id: entityId.value || undefined,
      anchor_name: anchorName.value,
      notes: anchorNotes.value,
    });
    await onListAssets();
    await onListAnchors();
    message.value = `anchor updated: ${assetId.value}`;
  } catch (error) {
    errorMessage.value = `anchor asset failed: ${stringifyError(error)}`;
  }
}

async function onListAnchors(): Promise<void> {
  clearNotice();
  try {
    const anchors = await listProjectAnchors(projectId.value, tenantId.value);
    anchorsText.value = JSON.stringify(anchors, null, 2);
  } catch (error) {
    errorMessage.value = `list anchors failed: ${stringifyError(error)}`;
  }
}

onMounted(async () => {
  try {
    novels.value = await listNovels(tenantId.value, projectId.value);
  } catch {
    // non-critical
  }
});
</script>
