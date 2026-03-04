<template>
  <div class="page-grid">
    <!-- ═══ 顶部筛选区 ═══ -->
    <NCard title="素材绑定一致性管理">
      <NGrid :cols="5" :x-gap="10" :y-gap="8" responsive="screen" item-responsive>
        <!-- Novel -->
        <NGridItem span="0:5 900:1">
          <NTooltip trigger="hover" placement="top">
            <template #trigger>
              <NFormItem label="小说">
                <NSelect
                  v-model:value="filterNovelId"
                  :options="novelOptions"
                  clearable
                  filterable
                  placeholder="全部小说"
                  @update:value="onNovelChange"
                />
              </NFormItem>
            </template>
            选择小说以缩小查询范围，级联过滤章节列表
          </NTooltip>
        </NGridItem>
        <!-- Chapter -->
        <NGridItem span="0:5 900:1">
          <NTooltip trigger="hover" placement="top">
            <template #trigger>
              <NFormItem label="章节">
                <NSelect
                  v-model:value="filterChapterId"
                  :options="chapterOptions"
                  clearable
                  filterable
                  placeholder="全部章节"
                />
              </NFormItem>
            </template>
            按章节过滤绑定记录（仅该章节出现的实体）
          </NTooltip>
        </NGridItem>
        <!-- Entity Type -->
        <NGridItem span="0:5 900:1">
          <NTooltip trigger="hover" placement="top">
            <template #trigger>
              <NFormItem label="实体类型">
                <NSelect
                  v-model:value="filterEntityType"
                  :options="entityTypeOptions"
                  clearable
                  placeholder="全部类型"
                />
              </NFormItem>
            </template>
            按实体类型过滤：人物/场景/道具/组织/其他
          </NTooltip>
        </NGridItem>
        <!-- Continuity Status -->
        <NGridItem span="0:5 900:1">
          <NTooltip trigger="hover" placement="top">
            <template #trigger>
              <NFormItem label="一致性状态">
                <NSelect
                  v-model:value="filterStatus"
                  :options="statusOptions"
                  clearable
                  placeholder="全部状态"
                />
              </NFormItem>
            </template>
            locked=已锁定素材 / drifted=与锁定素材偏差 / candidate=候选中 / unbound=未绑定
          </NTooltip>
        </NGridItem>
        <!-- Keyword -->
        <NGridItem span="0:5 900:1">
          <NTooltip trigger="hover" placement="top">
            <template #trigger>
              <NFormItem label="关键词">
                <NInput v-model:value="filterKeyword" placeholder="名称/URI/ID" clearable />
              </NFormItem>
            </template>
            模糊匹配实体名称、素材 URI 或实体 ID
          </NTooltip>
        </NGridItem>
      </NGrid>
      <NSpace>
        <NButton type="primary" @click="onLoadBindings">查询一致性</NButton>
        <NButton @click="onLoadAssetCandidates">查候选素材</NButton>
      </NSpace>
    </NCard>

    <!-- ═══ 中部绑定列表 ═══ -->
    <NCard title="绑定列表">
      <NDataTable
        :columns="bindingColumns"
        :data="bindings"
        :row-key="(row) => row.entity_id + (row.shot_id ?? '')"
        :pagination="{ pageSize: 15 }"
        size="small"
      />
    </NCard>

    <!-- ═══ 下部详情（选中后显示） ═══ -->
    <NCard v-if="selected" title="选中条目详情">
      <NTabs type="line" animated>

        <!-- Tab A: 实体详情 -->
        <NTabPane name="entity_detail" tab="实体详情">
          <NDescriptions :column="2" bordered size="small">
            <NDescriptionsItem label="规范名">{{ selected.entity_name }}</NDescriptionsItem>
            <NDescriptionsItem label="类型">{{ selected.entity_type }}</NDescriptionsItem>
            <NDescriptionsItem label="Entity ID">{{ selected.entity_id }}</NDescriptionsItem>
            <NDescriptionsItem label="一致性状态">
              <NTag :type="statusTagType(selected.continuity_status)" size="small">
                {{ selected.continuity_status }}
              </NTag>
            </NDescriptionsItem>
            <NDescriptionsItem label="章节">{{ selected.scene_label ?? '-' }}</NDescriptionsItem>
            <NDescriptionsItem label="Run ID">{{ selected.run_id ?? '-' }}</NDescriptionsItem>
          </NDescriptions>

          <!-- Entity Mapping detail (from entity_mappings table) -->
          <template v-if="selectedEntityMapping">
            <NDivider />
            <NDescriptions :column="2" bordered size="small" title="映射信息">
              <NDescriptionsItem label="别名">
                {{ (selectedEntityMapping.aliases_json ?? []).join('、') || '-' }}
              </NDescriptionsItem>
              <NDescriptionsItem label="多语言译名">
                <span style="font-size:11px">
                  {{ Object.entries(selectedEntityMapping.translations_json ?? {}).map(([k,v]) => `${k}:${v}`).join('  ') || '-' }}
                </span>
              </NDescriptionsItem>
              <NDescriptionsItem label="造型特征" :span="2">
                {{ selectedEntityMapping.notes || '-' }}
              </NDescriptionsItem>
            </NDescriptions>
          </template>
        </NTabPane>

        <!-- Tab B: 绑定素材 -->
        <NTabPane name="assets" tab="绑定素材">
          <NGrid :cols="2" :x-gap="16">
            <NGridItem>
              <NText depth="3" style="display:block;margin-bottom:8px;font-weight:600">锁定素材 (Anchor)</NText>
              <NText v-if="selected.locked_asset_uri" depth="3" style="display:block;font-size:11px;margin-bottom:8px;word-break:break-all">
                {{ selected.locked_asset_uri }}
              </NText>
              <NImage
                v-if="selected.locked_asset_uri"
                :src="selected.locked_asset_uri"
                :width="300"
                object-fit="contain"
                preview-disabled
              />
              <NEmpty v-else description="未锁定素材" />
            </NGridItem>
            <NGridItem>
              <NText depth="3" style="display:block;margin-bottom:8px;font-weight:600">最新素材 (Latest)</NText>
              <NText v-if="selected.latest_asset_uri" depth="3" style="display:block;font-size:11px;margin-bottom:8px;word-break:break-all">
                {{ selected.latest_asset_uri }}
              </NText>
              <NImage
                v-if="selected.latest_asset_uri"
                :src="selected.latest_asset_uri"
                :width="300"
                object-fit="contain"
                preview-disabled
              />
              <NEmpty v-else description="暂无最新素材" />
            </NGridItem>
          </NGrid>

          <!-- Bind / Replace / Unlock actions -->
          <NDivider />
          <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive style="margin-bottom:8px">
            <NGridItem span="0:2 900:1">
              <NFormItem label="Asset ID">
                <NInput v-model:value="anchorAssetId" placeholder="输入素材 ID" />
              </NFormItem>
            </NGridItem>
            <NGridItem span="0:2 900:1">
              <NFormItem label="Anchor Name">
                <NInput v-model:value="anchorName" />
              </NFormItem>
            </NGridItem>
          </NGrid>
          <NFormItem label="备注">
            <NInput v-model:value="anchorNotes" type="textarea" :autosize="{ minRows: 2, maxRows: 3 }" />
          </NFormItem>
          <NSpace>
            <NButton type="primary" @click="onApplyAnchor">绑定 / 替换锁定素材</NButton>
            <NButton type="warning" @click="onUnlockAnchor">解锁</NButton>
          </NSpace>
          <pre v-if="operationText !== '{}'" class="json-panel" style="margin-top:8px;font-size:11px">{{ operationText }}</pre>
        </NTabPane>

        <!-- Tab C: 一致性报告 -->
        <NTabPane name="consistency_report" tab="一致性报告">
          <template v-if="selected.continuity_status === 'drifted'">
            <NAlert type="warning" style="margin-bottom:12px">
              检测到漂移：最新素材与锁定素材不一致，建议重新锁定或重生成。
            </NAlert>
          </template>

          <NDivider>修复建议</NDivider>
          <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive style="margin-bottom:8px">
            <NGridItem span="0:2 900:1">
              <NFormItem label="视角 (逗号分隔)">
                <NInput v-model:value="viewAnglesCsv" placeholder="front,three_quarter,side" />
              </NFormItem>
            </NGridItem>
            <NGridItem span="0:2 900:1">
              <NFormItem label="Shot ID (可选)">
                <NInput v-model:value="regenShotId" placeholder="shot_xxx" />
              </NFormItem>
            </NGridItem>
          </NGrid>
          <NFormItem label="Prompt 覆盖（可选）">
            <NInput v-model:value="regenPrompt" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" />
          </NFormItem>
          <NFormItem label="Negative Prompt（可选）">
            <NInput v-model:value="regenNegativePrompt" type="textarea" :autosize="{ minRows: 2, maxRows: 3 }" />
          </NFormItem>
          <NSpace style="margin-bottom:12px">
            <NButton type="warning" @click="onRegenerateEntity">按实体重生成</NButton>
            <NButton @click="onRegenerateFromLatestVariant">按最近预览重生成</NButton>
          </NSpace>

          <!-- Candidates text -->
          <template v-if="assetCandidatesText !== '[]'">
            <NDivider>可锚定素材候选</NDivider>
            <pre class="json-panel" style="font-size:11px">{{ assetCandidatesText }}</pre>
          </template>
        </NTabPane>

      </NTabs>
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
  NDescriptions,
  NDescriptionsItem,
  NDivider,
  NEmpty,
  NFormItem,
  NGrid,
  NGridItem,
  NImage,
  NInput,
  NSelect,
  NSpace,
  NTabPane,
  NTabs,
  NTag,
  NText,
  NTooltip,
  type DataTableColumns,
} from "naive-ui";
import { useI18n } from "@/composables/useI18n";

import {
  type AssetBindingConsistencyItem,
  type ChapterResponse,
  type EntityMappingItem,
  type NovelResponse,
  generateEntityPreviewVariants,
  listAssetBindingConsistency,
  listEntityMappings,
  listNovels,
  listChapters,
  listProjectAssets,
  markAssetAnchor,
  reviewPreviewVariant,
} from "@/api/product";

const { t } = useI18n();

// ─── Filter state ──────────────────────────────────────────────────────────────
const tenantId = ref("default");
const projectId = ref("default");
const filterNovelId = ref<string | null>(null);
const filterChapterId = ref<string | null>(null);
const filterEntityType = ref<string | null>(null);
const filterStatus = ref<string | null>(null);
const filterKeyword = ref("");

// ─── Data state ────────────────────────────────────────────────────────────────
const novels = ref<NovelResponse[]>([]);
const chapters = ref<ChapterResponse[]>([]);
const bindings = ref<AssetBindingConsistencyItem[]>([]);
const selected = ref<AssetBindingConsistencyItem | null>(null);
const selectedEntityMapping = ref<EntityMappingItem | null>(null);

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

// ─── Selects ──────────────────────────────────────────────────────────────────
const novelOptions = computed(() =>
  novels.value.map(n => ({ label: n.title, value: n.id }))
);

const chapterOptions = computed(() =>
  chapters.value.map(c => ({
    label: `Ch.${c.chapter_no} ${c.title ?? ""}`.trim(),
    value: c.id,
  }))
);

const entityTypeOptions = [
  { label: "人物 (character)", value: "character" },
  { label: "人物 (person)", value: "person" },
  { label: "场景 (location)", value: "location" },
  { label: "道具 (prop)", value: "prop" },
  { label: "组织 (org)", value: "org" },
  { label: "其他", value: "other" },
];

const statusOptions = [
  { label: "未绑定 (unbound)", value: "unbound" },
  { label: "候选 (candidate)", value: "candidate" },
  { label: "已锁定 (locked)", value: "locked" },
  { label: "漂移 (drifted)", value: "drifted" },
];

function statusTagType(status: string): "default" | "info" | "success" | "warning" | "error" {
  const map: Record<string, "default" | "info" | "success" | "warning" | "error"> = {
    unbound: "default",
    candidate: "info",
    locked: "success",
    drifted: "warning",
  };
  return map[status] ?? "default";
}

// ─── Table columns ─────────────────────────────────────────────────────────────
const bindingColumns: DataTableColumns<AssetBindingConsistencyItem> = [
  {
    title: "实体（类型+名称）",
    key: "entity_name",
    render: (row) =>
      h("span", {}, [
        h(NTag, { size: "tiny", style: "margin-right:4px" }, { default: () => row.entity_type }),
        h("span", {}, row.entity_name),
      ]),
  },
  { title: "章节/场景", key: "scene_label", width: 100 },
  {
    title: "锁定素材 URI",
    key: "locked_asset_uri",
    render: (row) =>
      h("span", { style: "font-size:11px;color:#888;word-break:break-all" },
        row.locked_asset_uri ? row.locked_asset_uri.slice(-40) : "—"
      ),
  },
  {
    title: "最新素材 URI",
    key: "latest_asset_uri",
    render: (row) =>
      h("span", { style: "font-size:11px;color:#888;word-break:break-all" },
        row.latest_asset_uri ? row.latest_asset_uri.slice(-40) : "—"
      ),
  },
  {
    title: "状态",
    key: "continuity_status",
    width: 90,
    render: (row) =>
      h(NTag, { type: statusTagType(row.continuity_status), size: "small" }, {
        default: () => row.continuity_status,
      }),
  },
  {
    title: "操作",
    key: "action",
    width: 90,
    render: (row) =>
      h(NButton, {
        size: "small",
        type: "primary",
        onClick: () => void onSelectBinding(row),
      }, { default: () => "选中" }),
  },
];

// ─── Helpers ───────────────────────────────────────────────────────────────────
function stringifyError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function clearNotice(): void {
  message.value = "";
  errorMessage.value = "";
}

function parseCsv(value: string): string[] {
  return value.split(",").map(s => s.trim()).filter(Boolean);
}

// ─── Init ──────────────────────────────────────────────────────────────────────
onMounted(async () => {
  try {
    const novelList = await listNovels(tenantId.value, projectId.value);
    novels.value = novelList;
  } catch {
    // ignore
  }
});

async function onNovelChange(novelId: string | null): Promise<void> {
  filterChapterId.value = null;
  chapters.value = [];
  if (!novelId) return;
  try {
    chapters.value = await listChapters(novelId);
  } catch {
    // ignore
  }
}

// ─── API ───────────────────────────────────────────────────────────────────────
async function onLoadBindings(): Promise<void> {
  clearNotice();
  try {
    bindings.value = await listAssetBindingConsistency({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      chapter_id: filterChapterId.value || undefined,
      entity_type: filterEntityType.value || undefined,
      keyword: filterKeyword.value || undefined,
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
      chapter_id: filterChapterId.value || undefined,
      keyword: filterKeyword.value || undefined,
    });
    assetCandidatesText.value = JSON.stringify(rows, null, 2);
  } catch (error) {
    errorMessage.value = `list assets failed: ${stringifyError(error)}`;
  }
}

async function onSelectBinding(item: AssetBindingConsistencyItem): Promise<void> {
  selected.value = item;
  anchorAssetId.value = item.locked_asset_id || item.latest_asset_id || "";
  anchorName.value = item.anchor_name || "continuity-lock";
  anchorNotes.value = item.anchor_notes || "manual lock from consistency panel";
  regenShotId.value = item.shot_id || "";
  message.value = `已选中: ${item.entity_name}`;

  // Try to load entity mapping for extra detail
  selectedEntityMapping.value = null;
  if (filterNovelId.value) {
    try {
      const mappings = await listEntityMappings(filterNovelId.value, { keyword: item.entity_name });
      if (mappings.length > 0) {
        selectedEntityMapping.value = mappings[0];
      }
    } catch {
      // ignore
    }
  }
}

async function onApplyAnchor(): Promise<void> {
  clearNotice();
  if (!selected.value) {
    errorMessage.value = "请先选中实体";
    return;
  }
  if (!anchorAssetId.value) {
    errorMessage.value = "asset_id 不能为空";
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
    message.value = `锁定素材已更新: ${anchorAssetId.value}`;
  } catch (error) {
    errorMessage.value = `update anchor failed: ${stringifyError(error)}`;
  }
}

async function onUnlockAnchor(): Promise<void> {
  clearNotice();
  if (!selected.value) {
    errorMessage.value = "请先选中实体";
    return;
  }
  try {
    const resp = await markAssetAnchor("", {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      entity_id: selected.value.entity_id,
      anchor_name: "unlocked",
      notes: "manually unlocked",
    });
    operationText.value = JSON.stringify(resp, null, 2);
    await onLoadBindings();
    message.value = "已解锁素材绑定";
  } catch (error) {
    errorMessage.value = `unlock anchor failed: ${stringifyError(error)}`;
  }
}

async function onRegenerateEntity(): Promise<void> {
  clearNotice();
  if (!selected.value) {
    errorMessage.value = "请先选中实体";
    return;
  }
  const selectedRunId = selected.value.run_id || "";
  if (!selectedRunId) {
    errorMessage.value = "run_id 不能为空，请先完成渲染";
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
    message.value = "实体预览重生成已提交";
  } catch (error) {
    errorMessage.value = `regenerate entity failed: ${stringifyError(error)}`;
  }
}

async function onRegenerateFromLatestVariant(): Promise<void> {
  clearNotice();
  if (!selected.value?.latest_preview_variant_id) {
    errorMessage.value = "无最近预览变体可重生成";
    return;
  }
  try {
    const resp = await reviewPreviewVariant(selected.value.latest_preview_variant_id, {
      decision: "regenerate",
      note: "regenerate from consistency panel",
    });
    operationText.value = JSON.stringify(resp, null, 2);
    message.value = "预览变体重生成已请求";
  } catch (error) {
    errorMessage.value = `regenerate from variant failed: ${stringifyError(error)}`;
  }
}
</script>
