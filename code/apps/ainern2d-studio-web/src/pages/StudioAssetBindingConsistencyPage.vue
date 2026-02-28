<template>
  <div class="page-grid">
    <NCard title="素材-小说绑定一致性（人物/场景/道具）">
      <NGrid :cols="3" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Tenant ID"><NInput v-model:value="tenantId" /></NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Project ID"><NInput v-model:value="projectId" /></NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Chapter ID"><NInput v-model:value="chapterId" placeholder="optional" /></NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Run ID"><NInput v-model:value="runId" placeholder="optional" /></NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Entity Type">
            <NSelect v-model:value="entityType" :options="entityTypeOptions" clearable />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Keyword"><NInput v-model:value="keyword" placeholder="name / id / uri" /></NFormItem>
        </NGridItem>
      </NGrid>
      <NSpace>
        <NButton type="primary" @click="onLoadBindings">查询一致性</NButton>
        <NButton @click="onLoadAssetCandidates">查询可锚定素材</NButton>
      </NSpace>
    </NCard>

    <NCard title="绑定列表（可选中编辑）">
      <NDataTable :columns="bindingColumns" :data="bindings" :pagination="{ pageSize: 10 }" />
    </NCard>

    <NCard title="选中条目详情">
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 900:1">
          <NFormItem label="Entity">
            <NInput :value="selectedEntityLabel" readonly />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 900:1">
          <NFormItem label="Continuity Status">
            <NInput :value="selected?.continuity_status || ''" readonly />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 900:1">
          <NFormItem label="锁定素材 URI">
            <NInput :value="selected?.locked_asset_uri || ''" readonly />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 900:1">
          <NFormItem label="最新素材 URI">
            <NInput :value="selected?.latest_asset_uri || ''" readonly />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 900:1">
          <NImage
            v-if="selected?.locked_asset_uri"
            :src="selected.locked_asset_uri"
            :width="320"
            object-fit="contain"
            preview-disabled
          />
        </NGridItem>
        <NGridItem span="0:2 900:1">
          <NImage
            v-if="selected?.latest_asset_uri"
            :src="selected.latest_asset_uri"
            :width="320"
            object-fit="contain"
            preview-disabled
          />
        </NGridItem>
      </NGrid>
    </NCard>

    <NCard title="锁定素材编辑（Anchor）">
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 900:1">
          <NFormItem label="Asset ID"><NInput v-model:value="anchorAssetId" /></NFormItem>
        </NGridItem>
        <NGridItem span="0:2 900:1">
          <NFormItem label="Anchor Name"><NInput v-model:value="anchorName" /></NFormItem>
        </NGridItem>
      </NGrid>
      <NFormItem label="Anchor Notes">
        <NInput v-model:value="anchorNotes" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" />
      </NFormItem>
      <NSpace>
        <NButton type="primary" @click="onApplyAnchor">设为锁定素材</NButton>
      </NSpace>
      <pre class="json-panel">{{ assetCandidatesText }}</pre>
    </NCard>

    <NCard title="重生成（预览变体）">
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 900:1">
          <NFormItem label="View Angles (comma separated)">
            <NInput v-model:value="viewAnglesCsv" placeholder="front,three_quarter,side" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 900:1">
          <NFormItem label="Shot ID (optional)">
            <NInput v-model:value="regenShotId" placeholder="shot_xxx" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NFormItem label="Prompt Override (optional)">
        <NInput v-model:value="regenPrompt" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" />
      </NFormItem>
      <NFormItem label="Negative Prompt (optional)">
        <NInput v-model:value="regenNegativePrompt" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" />
      </NFormItem>
      <NSpace>
        <NButton type="warning" @click="onRegenerateEntity">按实体重生成</NButton>
        <NButton @click="onRegenerateFromLatestVariant">按最近预览重生成</NButton>
      </NSpace>
      <pre class="json-panel">{{ operationText }}</pre>
    </NCard>

    <NAlert v-if="message" type="success" :show-icon="true">{{ message }}</NAlert>
    <NAlert v-if="errorMessage" type="error" :show-icon="true">{{ errorMessage }}</NAlert>
  </div>
</template>

<script setup lang="ts">
import { computed, h, ref } from "vue";
import {
  NAlert,
  NButton,
  NCard,
  NDataTable,
  NFormItem,
  NGrid,
  NGridItem,
  NImage,
  NInput,
  NSelect,
  NSpace,
  type DataTableColumns,
} from "naive-ui";
import { useI18n } from "@/composables/useI18n";


import {
  type AssetBindingConsistencyItem,
  generateEntityPreviewVariants,
  listAssetBindingConsistency,
  listProjectAssets,
  markAssetAnchor,
  reviewPreviewVariant,
} from "@/api/product";

const { t } = useI18n();

const tenantId = ref("default");
const projectId = ref("default");
const chapterId = ref("");
const runId = ref("");
const keyword = ref("");
const entityType = ref<string | null>(null);

const bindings = ref<AssetBindingConsistencyItem[]>([]);
const selected = ref<AssetBindingConsistencyItem | null>(null);

const anchorAssetId = ref("");
const anchorName = ref("continuity-lock");
const anchorNotes = ref("manual lock from consistency panel");

const viewAnglesCsv = ref("front,three_quarter");
const regenShotId = ref("");
const regenPrompt = ref("");
const regenNegativePrompt = ref("");

const operationText = ref("{}");
const assetCandidatesText = ref("[]");

const message = ref("");
const errorMessage = ref("");

const entityTypeOptions = [
  { label: "人物 (person)", value: "person" },
  { label: "场景 (scene/place)", value: "scene" },
  { label: "道具 (prop/item)", value: "prop" },
  { label: "组织 (org)", value: "org" },
  { label: "其他", value: "other" },
];

const selectedEntityLabel = computed(() => {
  if (!selected.value) {
    return "";
  }
  return `${selected.value.entity_name} (${selected.value.entity_id})`;
});

const bindingColumns: DataTableColumns<AssetBindingConsistencyItem> = [
  { title: "Type", key: "entity_type" },
  { title: "Name", key: "entity_name" },
  { title: "Entity ID", key: "entity_id" },
  { title: "Scene", key: "scene_label" },
  { title: "Run", key: "run_id" },
  { title: "Shot", key: "shot_id" },
  { title: "Locked Asset", key: "locked_asset_id" },
  { title: "Latest Variant", key: "latest_preview_variant_id" },
  { title: "Status", key: "continuity_status" },
  {
    title: "Action",
    key: "action",
    render: (row) =>
      h(
        NButton,
        {
          size: "small",
          type: "info",
          onClick: () => onSelectBinding(row),
        },
        { default: () => "Select" }
      ),
  },
];

function stringifyError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function clearNotice(): void {
  message.value = "";
  errorMessage.value = "";
}

function parseCsv(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

function onSelectBinding(item: AssetBindingConsistencyItem): void {
  selected.value = item;
  anchorAssetId.value = item.locked_asset_id || item.latest_asset_id || "";
  anchorName.value = item.anchor_name || "continuity-lock";
  anchorNotes.value = item.anchor_notes || "manual lock from consistency panel";
  regenShotId.value = item.shot_id || "";
  message.value = `selected entity: ${item.entity_name}`;
}

async function onLoadBindings(): Promise<void> {
  clearNotice();
  try {
    bindings.value = await listAssetBindingConsistency({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      chapter_id: chapterId.value || undefined,
      run_id: runId.value || undefined,
      entity_type: entityType.value || undefined,
      keyword: keyword.value || undefined,
    });
  } catch (error) {
    errorMessage.value = `list consistency failed: ${stringifyError(error)}`;
  }
}

async function onLoadAssetCandidates(): Promise<void> {
  clearNotice();
  try {
    const rows = await listProjectAssets({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      chapter_id: chapterId.value || undefined,
      run_id: runId.value || undefined,
      keyword: keyword.value || undefined,
    });
    assetCandidatesText.value = JSON.stringify(rows, null, 2);
  } catch (error) {
    errorMessage.value = `list assets failed: ${stringifyError(error)}`;
  }
}

async function onApplyAnchor(): Promise<void> {
  clearNotice();
  if (!selected.value) {
    errorMessage.value = "select an entity first";
    return;
  }
  if (!anchorAssetId.value) {
    errorMessage.value = "asset_id is required";
    return;
  }
  try {
    const resp = await markAssetAnchor(anchorAssetId.value, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      entity_id: selected.value.entity_id,
      anchor_name: anchorName.value,
      notes: anchorNotes.value,
    });
    operationText.value = JSON.stringify(resp, null, 2);
    await onLoadBindings();
    message.value = `anchor updated: ${anchorAssetId.value}`;
  } catch (error) {
    errorMessage.value = `update anchor failed: ${stringifyError(error)}`;
  }
}

async function onRegenerateEntity(): Promise<void> {
  clearNotice();
  if (!selected.value) {
    errorMessage.value = "select an entity first";
    return;
  }
  const selectedRunId = selected.value.run_id || runId.value;
  if (!selectedRunId) {
    errorMessage.value = "run_id is required for regeneration";
    return;
  }
  try {
    const resp = await generateEntityPreviewVariants(selectedRunId, selected.value.entity_id, {
      shot_id: regenShotId.value || undefined,
      view_angles: parseCsv(viewAnglesCsv.value),
      prompt_text: regenPrompt.value || undefined,
      negative_prompt_text: regenNegativePrompt.value || undefined,
      generation_backend: "comfyui",
    });
    operationText.value = JSON.stringify(resp, null, 2);
    message.value = "entity preview regeneration queued";
  } catch (error) {
    errorMessage.value = `regenerate entity failed: ${stringifyError(error)}`;
  }
}

async function onRegenerateFromLatestVariant(): Promise<void> {
  clearNotice();
  if (!selected.value?.latest_preview_variant_id) {
    errorMessage.value = "no latest preview variant to regenerate";
    return;
  }
  try {
    const resp = await reviewPreviewVariant(selected.value.latest_preview_variant_id, {
      decision: "regenerate",
      note: "regenerate from consistency panel",
    });
    operationText.value = JSON.stringify(resp, null, 2);
    message.value = "preview variant regeneration requested";
  } catch (error) {
    errorMessage.value = `regenerate from variant failed: ${stringifyError(error)}`;
  }
}
</script>
