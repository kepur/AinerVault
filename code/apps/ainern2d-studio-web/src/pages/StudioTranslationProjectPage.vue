<template>
  <div class="page-grid">
    <NCard :title="`转译工作台 · ${projectId}`">
      <NSpace>
        <NButton @click="goBack">{{ t('common.back') }}</NButton>
        <NButton @click="onReload">{{ t('common.refresh') }}</NButton>
      </NSpace>
    </NCard>

    <NAlert v-if="projectError" type="error" :show-icon="true">{{ projectError }}</NAlert>

    <template v-if="project">
      <NTabs v-model:value="activeTab" type="card" animated>

        <!-- ════ Tab 1: 转译进度 ════ -->
        <NTabPane name="progress" :tab="t('trans.progress')">
          <NCard>
            <NSpace vertical size="large">

              <!-- Project info -->
              <NDescriptions bordered :column="3" label-placement="top" size="small">
                <NDescriptionsItem label="源语言">{{ project.source_language_code }}</NDescriptionsItem>
                <NDescriptionsItem label="目标语言">{{ project.target_language_code }}</NDescriptionsItem>
                <NDescriptionsItem label="状态">
                  <NTag :type="statusType(project.status)" size="small">{{ project.status }}</NTag>
                </NDescriptionsItem>
                <NDescriptionsItem label="一致性模式">{{ project.consistency_mode }}</NDescriptionsItem>
                <NDescriptionsItem label="Provider">{{ project.model_provider_id ?? "未配置" }}</NDescriptionsItem>
                <NDescriptionsItem label="告警数">
                  <NTag :type="openWarnings > 0 ? 'warning' : 'success'" size="small">
                    {{ openWarnings }} 条未解决
                  </NTag>
                </NDescriptionsItem>
              </NDescriptions>

              <!-- Stats -->
              <NGrid :cols="5" :x-gap="12">
                <NGridItem>
                  <NStatistic label="总块数" :value="stats.total" />
                </NGridItem>
                <NGridItem>
                  <NStatistic label="已翻译" :value="stats.translated" />
                </NGridItem>
                <NGridItem>
                  <NStatistic label="已审核" :value="stats.reviewed" />
                </NGridItem>
                <NGridItem>
                  <NStatistic label="已锁定" :value="stats.locked" />
                </NGridItem>
                <NGridItem>
                  <NStatistic label="未翻译" :value="stats.pending" />
                </NGridItem>
              </NGrid>

              <!-- Progress bar -->
              <NProgress
                v-if="stats.total > 0"
                type="line"
                :percentage="Math.round((stats.translated / stats.total) * 100)"
                :indicator-placement="'inside'"
                processing
              />

              <!-- Operations -->
              <NDivider>操作</NDivider>
              <NSpace>
                <NSelect
                  v-model:value="selectedChapterId"
                  :options="chapterOptions"
                  clearable
                  placeholder="选择章节（不选=全部）"
                  style="width: 240px"
                />
                <NButton
                  type="default"
                  :loading="isSegmenting"
                  @click="onSegment"
                >
                  {{ isSegmenting ? "分块中..." : "一键分块" }}
                </NButton>
                <NButton
                  type="primary"
                  :loading="isTranslating"
                  :disabled="!project.model_provider_id"
                  @click="onTranslate"
                >
                  {{ isTranslating ? "翻译中（约90s）..." : "一键翻译" }}
                </NButton>
              </NSpace>

              <NAlert v-if="!project.model_provider_id" type="warning">
                请先在「术语词典」Tab 或小说详情配置 Provider ID，再使用一键翻译。
              </NAlert>

              <NAlert v-if="opMessage" type="success">{{ opMessage }}</NAlert>
              <NAlert v-if="opError" type="error">{{ opError }}</NAlert>
            </NSpace>
          </NCard>
        </NTabPane>

        <!-- ════ Tab 2: 转译剧本 ════ -->
        <NTabPane name="script" :tab="t('trans.script')">
          <NCard>
            <NSpace vertical>
              <NSpace>
                <NSelect
                  v-model:value="scriptChapterId"
                  :options="chapterOptions"
                  clearable
                  placeholder="选择章节"
                  style="width: 240px"
                  @update:value="onLoadBlocks"
                />
                <NButton @click="onLoadBlocks">加载</NButton>
                <NButton type="primary" :loading="isSavingBlocks" @click="onSaveAllBlocks">
                  保存所有修改
                </NButton>
              </NSpace>

              <NAlert v-if="blockSaveMessage" type="success">{{ blockSaveMessage }}</NAlert>
              <NAlert v-if="blockError" type="error">{{ blockError }}</NAlert>

              <NDataTable
                :columns="blockColumns"
                :data="scriptBlocks"
                :pagination="{ pageSize: 20 }"
                :row-key="(row) => row.id"
                size="small"
              />
            </NSpace>
          </NCard>
        </NTabPane>

        <!-- ════ Tab 3: 一致性中心 ════ -->
        <NTabPane name="consistency" :tab="t('trans.consistency')">
          <NTabs type="segment" animated>

            <!-- Sub-Tab: 实体变体 -->
            <NTabPane name="variants" :tab="t('trans.entityVariants')">
              <NCard>
                <NSpace vertical>
                  <!-- Add variant form -->
                  <NSpace align="center">
                    <NInput v-model:value="newVariantSource" placeholder="原文名称" style="width:160px" />
                    <NInput v-model:value="newVariantCanonical" placeholder="规范译名" style="width:160px" />
                    <NButton type="primary" @click="onAddVariant">添加变体</NButton>
                  </NSpace>

                  <NAlert v-if="variantMessage" type="success">{{ variantMessage }}</NAlert>
                  <NAlert v-if="variantError" type="error">{{ variantError }}</NAlert>

                  <NDataTable
                    :columns="variantColumns"
                    :data="entityVariants"
                    :pagination="{ pageSize: 15 }"
                    size="small"
                  />
                </NSpace>
              </NCard>
            </NTabPane>

            <!-- Sub-Tab: 告警 -->
            <NTabPane name="warnings" tab="告警列表">
              <NCard>
                <NSpace vertical>
                  <NSpace>
                    <NSelect
                      v-model:value="warningStatusFilter"
                      :options="warningStatusOptions"
                      style="width: 150px"
                      @update:value="onLoadWarnings"
                    />
                    <NButton :loading="isCheckingConsistency" @click="onCheckConsistency">
                      重新检查
                    </NButton>
                  </NSpace>

                  <NAlert v-if="warningMessage" type="success">{{ warningMessage }}</NAlert>
                  <NAlert v-if="warningError" type="error">{{ warningError }}</NAlert>

                  <NDataTable
                    :columns="warningColumns"
                    :data="warnings"
                    :pagination="{ pageSize: 15 }"
                    size="small"
                  />
                </NSpace>
              </NCard>
            </NTabPane>

          </NTabs>
        </NTabPane>

        <!-- ════ Tab 4: 术语词典 ════ -->
        <NTabPane name="dict" tab="术语词典">
          <NCard>
            <NSpace vertical>
              <NText depth="3">
                译前注入 LLM 的专名对照表，翻译时将强制遵守。保存后下次翻译生效。
              </NText>

              <NDataTable
                :columns="dictColumns"
                :data="termRows"
                size="small"
                :pagination="false"
              />

              <NSpace>
                <NButton @click="onAddTermRow">+ 新增术语</NButton>
                <NButton type="primary" :loading="isSavingDict" @click="onSaveDict">保存词典</NButton>
              </NSpace>

              <NAlert v-if="dictMessage" type="success">{{ dictMessage }}</NAlert>
              <NAlert v-if="dictError" type="error">{{ dictError }}</NAlert>
            </NSpace>
          </NCard>
        </NTabPane>

      </NTabs>
    </template>
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
  NDescriptions,
  NDescriptionsItem,
  NDivider,
  NGrid,
  NGridItem,
  NInput,
  NProgress,
  NSelect,
  NSpace,
  NStatistic,
  NTabPane,
  NTabs,
  NTag,
  NText,
  type DataTableColumns,
} from "naive-ui";
import { useI18n } from "@/composables/useI18n";


import {
  checkConsistency,
  createEntityVariant,
  listConsistencyWarnings,
  listEntityVariants,
  listScriptBlocks,
  lockEntityVariant,
  resolveWarning,
  segmentChapters,
  translateBlocks,
  updateTranslationBlock,
  updateTranslationProject,
  type ConsistencyWarningResponse,
  type EntityNameVariantResponse,
  type ScriptBlockResponse,
  type TranslationProjectResponse,
} from "@/api/product";

import { http } from "@/api/http";

const props = defineProps<{ projectId: string }>();
const { t } = useI18n();

const router = useRouter();

// ─── State ────────────────────────────────────────────────────────────────────
const activeTab = ref("progress");
const project = ref<TranslationProjectResponse | null>(null);
const projectError = ref("");
const opMessage = ref("");
const opError = ref("");

// Chapters (fetched from novel)
const chapters = ref<{ label: string; value: string }[]>([]);
const selectedChapterId = ref<string | null>(null);

// Segment / Translate
const isSegmenting = ref(false);
const isTranslating = ref(false);

// Script blocks tab
const scriptChapterId = ref<string | null>(null);
const scriptBlocks = ref<ScriptBlockResponse[]>([]);
const isSavingBlocks = ref(false);
const blockEdits = ref<Record<string, { translated_text: string; status: string }>>({});
const blockSaveMessage = ref("");
const blockError = ref("");

// Consistency / Variants
const entityVariants = ref<EntityNameVariantResponse[]>([]);
const newVariantSource = ref("");
const newVariantCanonical = ref("");
const variantMessage = ref("");
const variantError = ref("");
const editingCanonical = ref<Record<string, string>>({});

// Warnings
const warnings = ref<ConsistencyWarningResponse[]>([]);
const warningStatusFilter = ref("open");
const isCheckingConsistency = ref(false);
const warningMessage = ref("");
const warningError = ref("");

// Dictionary
const termRows = ref<{ source: string; target: string; _key: number }[]>([]);
const isSavingDict = ref(false);
const dictMessage = ref("");
const dictError = ref("");
let _termKey = 0;

// ─── Options ──────────────────────────────────────────────────────────────────
const chapterOptions = computed(() => chapters.value);

const warningStatusOptions = [
  { label: "未解决 (open)", value: "open" },
  { label: "已解决 (resolved)", value: "resolved" },
  { label: "已忽略 (ignored)", value: "ignored" },
];

const BLOCK_TYPE_LABELS: Record<string, string> = {
  narration: "叙述",
  dialogue: "对白",
  action: "动作",
  heading: "标题",
  scene_break: "场景分隔",
};

const STATUS_TYPE_MAP: Record<string, "default" | "info" | "success" | "warning" | "error"> = {
  draft: "default",
  in_progress: "info",
  completed: "success",
  archived: "warning",
  reviewed: "info",
  locked: "success",
  open: "warning",
  resolved: "success",
  ignored: "default",
};

// ─── Computed ─────────────────────────────────────────────────────────────────
const stats = computed(() => {
  const total = scriptBlocks.value.length;
  const withTranslation = scriptBlocks.value.filter(b => b.translation);
  const reviewed = withTranslation.filter(b => b.translation?.status === "reviewed").length;
  const locked = withTranslation.filter(b => b.translation?.status === "locked").length;
  const translated = withTranslation.length;
  return {
    total,
    translated,
    reviewed,
    locked,
    pending: total - translated,
  };
});

const openWarnings = computed(() =>
  warnings.value.filter(w => w.status === "open").length
);

// ─── Helpers ──────────────────────────────────────────────────────────────────
function statusType(status: string): "default" | "info" | "success" | "warning" | "error" {
  return STATUS_TYPE_MAP[status] ?? "default";
}

function stringifyError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function clearOp(): void {
  opMessage.value = "";
  opError.value = "";
}

function goBack(): void {
  if (project.value) {
    void router.push({
      name: "studio-novel-detail",
      params: { novelId: project.value.novel_id },
      query: { tab: "translation" },
    });
  } else {
    void router.back();
  }
}

// ─── Load ─────────────────────────────────────────────────────────────────────
async function onReload(): Promise<void> {
  clearOp();
  try {
    // Load project (using list endpoint filtered by id is not ideal,
    // but we have a direct GET endpoint too)
    const { data } = await http.get<TranslationProjectResponse>(
      `/api/v1/translations/projects/${props.projectId}`
    );
    project.value = data;

    // Load novel chapters
    const chaptersResp = await http.get<{ id: string; chapter_no: number; title: string | null }[]>(
      `/api/v1/novels/${data.novel_id}/chapters`
    );
    chapters.value = chaptersResp.data.map(c => ({
      label: `第${c.chapter_no}章 ${c.title ?? ""}`.trim(),
      value: c.id,
    }));

    // Load term dictionary
    if (data.term_dictionary_json) {
      termRows.value = Object.entries(data.term_dictionary_json).map(([src, tgt]) => ({
        source: src,
        target: tgt as string,
        _key: _termKey++,
      }));
    }

    // Load all blocks (for stats)
    await onLoadAllBlocks();
    await onLoadVariants();
    await onLoadWarnings();
  } catch (error) {
    projectError.value = `加载失败: ${stringifyError(error)}`;
  }
}

async function onLoadAllBlocks(): Promise<void> {
  if (!project.value) return;
  try {
    scriptBlocks.value = await listScriptBlocks(props.projectId, {});
    // Init edits map
    blockEdits.value = {};
    for (const sb of scriptBlocks.value) {
      blockEdits.value[sb.id] = {
        translated_text: sb.translation?.translated_text ?? "",
        status: sb.translation?.status ?? "draft",
      };
    }
  } catch {
    // ignore
  }
}

async function onLoadBlocks(): Promise<void> {
  blockError.value = "";
  blockSaveMessage.value = "";
  try {
    scriptBlocks.value = await listScriptBlocks(props.projectId, {
      chapter_id: scriptChapterId.value ?? undefined,
    });
    blockEdits.value = {};
    for (const sb of scriptBlocks.value) {
      blockEdits.value[sb.id] = {
        translated_text: sb.translation?.translated_text ?? "",
        status: sb.translation?.status ?? "draft",
      };
    }
  } catch (error) {
    blockError.value = `加载块失败: ${stringifyError(error)}`;
  }
}

async function onLoadVariants(): Promise<void> {
  variantError.value = "";
  try {
    entityVariants.value = await listEntityVariants(props.projectId, {});
    editingCanonical.value = {};
    for (const v of entityVariants.value) {
      editingCanonical.value[v.id] = v.canonical_target_name;
    }
  } catch (error) {
    variantError.value = `加载变体失败: ${stringifyError(error)}`;
  }
}

async function onLoadWarnings(): Promise<void> {
  warningError.value = "";
  try {
    warnings.value = await listConsistencyWarnings(props.projectId, {
      status: warningStatusFilter.value,
    });
  } catch (error) {
    warningError.value = `加载告警失败: ${stringifyError(error)}`;
  }
}

// ─── Operations ───────────────────────────────────────────────────────────────
async function onSegment(): Promise<void> {
  clearOp();
  isSegmenting.value = true;
  try {
    const result = await segmentChapters(props.projectId, {
      chapter_id: selectedChapterId.value ?? undefined,
    });
    opMessage.value = `分块完成：共创建 ${result.blocks_created} 个块`;
    await onLoadAllBlocks();
  } catch (error) {
    opError.value = `分块失败: ${stringifyError(error)}`;
  } finally {
    isSegmenting.value = false;
  }
}

async function onTranslate(): Promise<void> {
  clearOp();
  isTranslating.value = true;
  try {
    const result = await translateBlocks(props.projectId, {
      chapter_id: selectedChapterId.value ?? undefined,
      batch_size: 10,
    });
    opMessage.value = `翻译完成：${result.translated} 块，${result.warnings} 条告警`;
    await onLoadAllBlocks();
    await onLoadWarnings();
    // Refresh project status
    const { data } = await http.get<TranslationProjectResponse>(
      `/api/v1/translations/projects/${props.projectId}`
    );
    project.value = data;
  } catch (error) {
    opError.value = `翻译失败: ${stringifyError(error)}`;
  } finally {
    isTranslating.value = false;
  }
}

async function onSaveAllBlocks(): Promise<void> {
  blockError.value = "";
  blockSaveMessage.value = "";
  isSavingBlocks.value = true;
  let saved = 0;
  try {
    for (const sb of scriptBlocks.value) {
      if (!sb.translation) continue;
      const edit = blockEdits.value[sb.id];
      if (!edit) continue;
      if (
        edit.translated_text === sb.translation.translated_text &&
        edit.status === sb.translation.status
      )
        continue;
      await updateTranslationBlock(props.projectId, sb.translation.id, {
        translated_text: edit.translated_text,
        status: edit.status,
      });
      saved++;
    }
    blockSaveMessage.value = `已保存 ${saved} 处修改`;
    await onLoadBlocks();
  } catch (error) {
    blockError.value = `保存失败: ${stringifyError(error)}`;
  } finally {
    isSavingBlocks.value = false;
  }
}

async function onAddVariant(): Promise<void> {
  variantMessage.value = "";
  variantError.value = "";
  if (!newVariantSource.value || !newVariantCanonical.value) {
    variantError.value = "请填写原文名称和规范译名";
    return;
  }
  try {
    await createEntityVariant(props.projectId, {
      source_name: newVariantSource.value,
      canonical_target_name: newVariantCanonical.value,
    });
    newVariantSource.value = "";
    newVariantCanonical.value = "";
    variantMessage.value = "变体已添加";
    await onLoadVariants();
  } catch (error) {
    variantError.value = `添加失败: ${stringifyError(error)}`;
  }
}

async function onLockVariant(variantId: string): Promise<void> {
  variantMessage.value = "";
  variantError.value = "";
  try {
    const canonical = editingCanonical.value[variantId] ?? "";
    await lockEntityVariant(props.projectId, variantId, { canonical_target_name: canonical });
    variantMessage.value = "已锁定规范名";
    await onLoadVariants();
  } catch (error) {
    variantError.value = `锁定失败: ${stringifyError(error)}`;
  }
}

async function onCheckConsistency(): Promise<void> {
  warningMessage.value = "";
  warningError.value = "";
  isCheckingConsistency.value = true;
  try {
    const result = await checkConsistency(props.projectId);
    warningMessage.value = `一致性检查完成，新增 ${result.warnings_created} 条告警`;
    await onLoadWarnings();
  } catch (error) {
    warningError.value = `检查失败: ${stringifyError(error)}`;
  } finally {
    isCheckingConsistency.value = false;
  }
}

async function onResolveWarning(warningId: string, status: "resolved" | "ignored"): Promise<void> {
  try {
    await resolveWarning(props.projectId, warningId, { status });
    warningMessage.value = `告警已${status === "resolved" ? "解决" : "忽略"}`;
    await onLoadWarnings();
  } catch (error) {
    warningError.value = `操作失败: ${stringifyError(error)}`;
  }
}

function onAddTermRow(): void {
  termRows.value.push({ source: "", target: "", _key: _termKey++ });
}

async function onSaveDict(): Promise<void> {
  dictMessage.value = "";
  dictError.value = "";
  isSavingDict.value = true;
  try {
    const dict: Record<string, string> = {};
    for (const row of termRows.value) {
      if (row.source.trim() && row.target.trim()) {
        dict[row.source.trim()] = row.target.trim();
      }
    }
    await updateTranslationProject(props.projectId, { term_dictionary_json: dict });
    dictMessage.value = `词典已保存（${Object.keys(dict).length} 条术语）`;
    if (project.value) {
      project.value.term_dictionary_json = dict;
    }
  } catch (error) {
    dictError.value = `保存失败: ${stringifyError(error)}`;
  } finally {
    isSavingDict.value = false;
  }
}

function onRemoveTermRow(key: number): void {
  termRows.value = termRows.value.filter(r => r._key !== key);
}

// ─── Table columns ─────────────────────────────────────────────────────────────

const BLOCK_STATUS_OPTIONS = [
  { label: "草稿", value: "draft" },
  { label: "已审核", value: "reviewed" },
  { label: "已锁定", value: "locked" },
];

const blockColumns: DataTableColumns<ScriptBlockResponse> = [
  {
    title: "类型",
    key: "block_type",
    width: 80,
    render: (row) =>
      h(NTag, { size: "small", type: "info" }, {
        default: () => BLOCK_TYPE_LABELS[row.block_type] ?? row.block_type,
      }),
  },
  {
    title: "说话人",
    key: "speaker_tag",
    width: 90,
    render: (row) => row.speaker_tag ?? "",
  },
  {
    title: "原文",
    key: "source_text",
    render: (row) =>
      h("div", { style: "white-space:pre-wrap;font-size:12px;max-height:100px;overflow-y:auto" }, row.source_text),
  },
  {
    title: "译文",
    key: "translated_text",
    render: (row) => {
      const edit = blockEdits.value[row.id];
      return h("textarea", {
        style: "width:100%;min-height:60px;font-size:12px;resize:vertical;border:1px solid #ccc;border-radius:4px;padding:4px",
        value: edit?.translated_text ?? "",
        onInput: (e: Event) => {
          const target = e.target as HTMLTextAreaElement;
          if (blockEdits.value[row.id]) {
            blockEdits.value[row.id].translated_text = target.value;
          }
        },
      });
    },
  },
  {
    title: "状态",
    key: "status",
    width: 110,
    render: (row) => {
      const edit = blockEdits.value[row.id];
      if (!edit) return h("span", {}, "—");
      return h(NSelect, {
        size: "small",
        value: edit.status,
        options: BLOCK_STATUS_OPTIONS,
        style: "width:100px",
        onUpdateValue: (v: string) => {
          blockEdits.value[row.id].status = v;
        },
      });
    },
  },
];

const variantColumns: DataTableColumns<EntityNameVariantResponse> = [
  { title: "原文名称", key: "source_name", width: 160 },
  {
    title: "规范译名",
    key: "canonical_target_name",
    render: (row) =>
      h(NInput, {
        size: "small",
        value: editingCanonical.value[row.id] ?? row.canonical_target_name,
        onUpdateValue: (v: string) => {
          editingCanonical.value[row.id] = v;
        },
      }),
  },
  {
    title: "锁定",
    key: "is_locked",
    width: 70,
    render: (row) =>
      h(NTag, {
        type: row.is_locked ? "success" : "default",
        size: "small",
      }, { default: () => (row.is_locked ? "已锁" : "未锁") }),
  },
  {
    title: "操作",
    key: "action",
    width: 90,
    render: (row) =>
      h(NButton, {
        size: "small",
        type: row.is_locked ? "default" : "primary",
        onClick: () => void onLockVariant(row.id),
      }, { default: () => "锁定规范名" }),
  },
];

const warningColumns: DataTableColumns<ConsistencyWarningResponse> = [
  {
    title: "类型",
    key: "warning_type",
    width: 100,
    render: (row) =>
      h(NTag, { type: "warning", size: "small" }, { default: () => row.warning_type }),
  },
  { title: "源词", key: "source_name", width: 120 },
  { title: "检测到变体", key: "detected_variant", width: 120 },
  { title: "期望规范词", key: "expected_canonical", width: 120 },
  {
    title: "状态",
    key: "status",
    width: 80,
    render: (row) =>
      h(NTag, { type: statusType(row.status), size: "small" }, { default: () => row.status }),
  },
  {
    title: "操作",
    key: "action",
    width: 140,
    render: (row) =>
      h(NSpace, { size: 4 }, {
        default: () => [
          h(NButton, {
            size: "tiny",
            type: "success",
            disabled: row.status !== "open",
            onClick: () => void onResolveWarning(row.id, "resolved"),
          }, { default: () => "解决" }),
          h(NButton, {
            size: "tiny",
            type: "default",
            disabled: row.status !== "open",
            onClick: () => void onResolveWarning(row.id, "ignored"),
          }, { default: () => "忽略" }),
        ],
      }),
  },
];

const dictColumns: DataTableColumns<{ source: string; target: string; _key: number }> = [
  {
    title: "原词（源语言）",
    key: "source",
    render: (row) =>
      h(NInput, {
        size: "small",
        value: row.source,
        placeholder: "原文术语",
        onUpdateValue: (v: string) => {
          const found = termRows.value.find(r => r._key === row._key);
          if (found) found.source = v;
        },
      }),
  },
  {
    title: "译词（目标语言）",
    key: "target",
    render: (row) =>
      h(NInput, {
        size: "small",
        value: row.target,
        placeholder: "译文术语",
        onUpdateValue: (v: string) => {
          const found = termRows.value.find(r => r._key === row._key);
          if (found) found.target = v;
        },
      }),
  },
  {
    title: "操作",
    key: "action",
    width: 80,
    render: (row) =>
      h(NButton, {
        size: "small",
        type: "error",
        onClick: () => onRemoveTermRow(row._key),
      }, { default: () => "删除" }),
  },
];

// ─── Lifecycle ─────────────────────────────────────────────────────────────────
onMounted(() => {
  void onReload();
});
</script>

<style scoped>
.page-grid {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px;
}
</style>
