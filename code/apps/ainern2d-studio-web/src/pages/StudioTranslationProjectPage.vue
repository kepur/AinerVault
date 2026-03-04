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
              <NSpace wrap>
                <NSelect
                  v-model:value="selectedChapterIds"
                  :options="chapterOptions"
                  multiple
                  clearable
                  placeholder="选择文章任务（可多选）"
                  style="width: 320px"
                />
                <NButton size="small" @click="onSelectAllChapters">全选章节</NButton>
                <NButton size="small" quaternary @click="selectedChapterIds = []">清空选择</NButton>
                <NButton
                  type="default"
                  :loading="isSegmenting"
                  :disabled="selectedChapterIds.length === 0"
                  @click="onSegment"
                >
                  {{ isSegmenting ? "分块中..." : "分块所选文章" }}
                </NButton>
                <NButton
                  type="primary"
                  :loading="isTranslating"
                  :disabled="!effectiveModelProviderId || selectedChapterIds.length === 0"
                  @click="onTranslate"
                >
                  {{ isTranslating ? "翻译中（约90s）..." : "翻译所选文章" }}
                </NButton>
                <NText depth="3" style="font-size:12px">
                  已选 {{ selectedChapterIds.length }} / {{ chapterOptions.length }} 章
                </NText>
              </NSpace>
              <NSpace wrap>
                <NButton
                  type="primary"
                  :loading="isExecutingPlan"
                  :disabled="!effectiveModelProviderId"
                  @click="onExecutePlan('pending')"
                >
                  执行下一批（pending）
                </NButton>
                <NButton
                  :loading="isExecutingPlan"
                  :disabled="!effectiveModelProviderId || selectedChapterIds.length === 0"
                  @click="onExecutePlan('selected')"
                >
                  执行选中章节任务
                </NButton>
                <NButton
                  :loading="isExecutingPlan"
                  :disabled="!effectiveModelProviderId"
                  @click="onExecutePlan('failed')"
                >
                  仅重试失败
                </NButton>
                <NButton
                  :loading="isExecutingPlan"
                  :disabled="!effectiveModelProviderId"
                  @click="onExecutePlan('untranslated')"
                >
                  仅执行未翻译
                </NButton>
                <NSelect
                  v-model:value="executionProviderId"
                  :options="providerOptions"
                  clearable
                  placeholder="执行 Provider（可覆盖）"
                  style="width: 220px"
                />
                <NButton
                  type="warning"
                  ghost
                  :loading="isCleaningJobs"
                  @click="onBatchRetryFailedJobs"
                >
                  批量重试失败任务
                </NButton>
                <NButton
                  type="error"
                  ghost
                  :loading="isCleaningJobs"
                  @click="onBatchDeleteFailedJobs"
                >
                  批量删除失败/已跳过
                </NButton>
                <NText depth="3" style="font-size:12px;line-height:34px">
                  计划项：总 {{ planStats.total }} / 待执行 {{ planStats.pending }} / 失败 {{ planStats.failed }}
                </NText>
              </NSpace>
              <NDataTable
                :columns="planColumns"
                :data="planItems"
                :row-key="(row: TranslationPlanItemResponse) => row.id"
                :checked-row-keys="selectedPlanItemIds"
                @update:checked-row-keys="onUpdateSelectedPlanItemIds"
                :pagination="{ pageSize: 8 }"
                size="small"
              />

              <NAlert v-if="!effectiveModelProviderId" type="warning">
                请先选择执行 Provider，或在「术语词典」Tab / 小说详情中配置默认 Provider ID。
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
              <NAlert type="info" :show-icon="false">
                本页只翻译面向观众的文本（对白/旁白/屏幕文字）。镜头、BGM、SFX、氛围等制作指令请在「制作计划 Plans」中查看与生成。
              </NAlert>

              <!-- Filter + actions bar -->
              <NSpace wrap align="center">
                <NSelect
                  v-model:value="scriptChapterId"
                  :options="chapterOptions"
                  clearable
                  placeholder="选择章节"
                  style="width: 200px"
                  @update:value="onLoadBlocks"
                />
                <NSelect
                  v-model:value="blockTypeFilter"
                  :options="blockTypeFilterOptions"
                  clearable
                  placeholder="类型筛选"
                  style="width: 130px"
                />
                <NButton size="small" @click="onLoadBlocks">加载</NButton>
                <NButton size="small" type="primary" :loading="isSavingBlocks" @click="onSaveAllBlocks">
                  保存全部修改
                </NButton>
                <NDivider vertical />
                <NText depth="3" style="font-size: 12px">切换 LLM：</NText>
                <NSelect
                  v-model:value="retranslateProviderId"
                  :options="providerOptions"
                  clearable
                  placeholder="Provider（可覆盖）"
                  style="width: 200px"
                />
              </NSpace>

              <NAlert v-if="blockSaveMessage" type="success">{{ blockSaveMessage }}</NAlert>
              <NAlert v-if="blockError" type="error">{{ blockError }}</NAlert>

              <!-- Paired source/target cards -->
              <div v-if="filteredBlocks.length === 0 && !isSavingBlocks">
                <NEmpty description="暂无内容，请选择章节后点击加载" />
              </div>
              <div
                v-for="block in filteredBlocks"
                :key="block.id"
                class="block-pair"
              >
                <!-- Block header -->
                <div class="block-header">
                  <NTag :type="blockTypeTag(block.block_type)" size="small">
                    {{ BLOCK_TYPE_LABELS[block.block_type] ?? block.block_type }}
                  </NTag>
                  <NText v-if="block.speaker_tag" depth="3" style="font-size: 12px; margin-left: 8px">
                    {{ block.speaker_tag }}
                  </NText>
                  <NTag
                    :type="block.translation ? statusType(block.translation.status) : 'default'"
                    size="tiny"
                    style="margin-left: auto"
                  >
                    {{ block.translation ? block.translation.status : '未翻译' }}
                  </NTag>
                </div>

                <!-- Source text (gray) -->
                <div class="source-text">{{ block.source_text }}</div>

                <!-- Target text (editable) -->
                <div class="target-area">
                  <NInput
                    v-if="blockEdits[block.id]"
                    v-model:value="blockEdits[block.id].translated_text"
                    type="textarea"
                    :autosize="{ minRows: 2, maxRows: 6 }"
                    :placeholder="block.translation ? '修改译文...' : '暂无译文，点击重新翻译'"
                    :readonly="!block.translation"
                    size="small"
                  />
                  <NText v-else depth="3" style="font-size: 12px; padding: 6px">暂无译文</NText>
                </div>

                <!-- Block actions -->
                <div class="block-actions">
                  <NSelect
                    v-if="block.translation && blockEdits[block.id]"
                    v-model:value="blockEdits[block.id].status"
                    :options="BLOCK_STATUS_OPTIONS"
                    size="tiny"
                    style="width: 100px"
                  />
                  <div style="flex: 1" />
                  <NButton
                    v-if="block.translation"
                    size="tiny"
                    type="error"
                    ghost
                    :loading="deletingBlockId === block.translation.id"
                    @click="onDeleteBlockTranslation(block)"
                  >
                    删除译文
                  </NButton>
                  <NButton
                    size="tiny"
                    type="warning"
                    ghost
                    :loading="retranslatingBlockId === block.id"
                    @click="onRetranslateBlock(block)"
                  >
                    {{ block.translation ? '重新翻译' : '翻译此块' }}
                  </NButton>
                  <NButton
                    v-if="block.translation && blockEdits[block.id]"
                    size="tiny"
                    type="primary"
                    @click="onSaveBlock(block)"
                  >
                    保存
                  </NButton>
                </div>
              </div>
            </NSpace>
          </NCard>
        </NTabPane>

        <!-- ════ Tab 3: 制作计划 Plans（只读） ════ -->
        <NTabPane name="plans" tab="制作计划 Plans">
          <NCard>
            <NSpace vertical size="large">
              <NAlert type="info" :show-icon="false">
                Plans 为生成侧数据（分镜/对白节奏/BGM/SFX/氛围）。此处为只读聚合视图，数据来自章节预览计划与运行时间线。
              </NAlert>

              <NSpace wrap align="center">
                <NSelect
                  v-model:value="plansChapterId"
                  :options="chapterOptions"
                  clearable
                  placeholder="选择章节加载 shot/scene 计划"
                  style="width: 260px"
                />
                <NButton :loading="isLoadingPreviewPlan" type="primary" @click="onLoadPreviewPlan">
                  加载章节 Plans
                </NButton>
                <NText depth="3" style="font-size:12px">
                  shot {{ previewPlanData?.shot_count ?? 0 }} / scene {{ previewPlanData?.scene_count ?? 0 }}
                </NText>
              </NSpace>

              <NAlert v-if="previewPlanError" type="error">{{ previewPlanError }}</NAlert>

              <template v-if="previewPlanData">
                <NGrid :cols="4" :x-gap="12">
                  <NGridItem>
                    <NStatistic label="Scenes" :value="previewPlanData.scene_count" />
                  </NGridItem>
                  <NGridItem>
                    <NStatistic label="Shots" :value="previewPlanData.shot_count" />
                  </NGridItem>
                  <NGridItem>
                    <NStatistic label="Skill03" :value="previewPlanData.skill_03_status" />
                  </NGridItem>
                  <NGridItem>
                    <NStatistic label="Preview Run" :value="previewPlanData.preview_run_id || '-'" />
                  </NGridItem>
                </NGrid>

                <NDivider>Shot Plan</NDivider>
                <NDataTable
                  :columns="shotPlanColumns"
                  :data="shotPlanRows"
                  :pagination="{ pageSize: 8 }"
                  size="small"
                />

                <NDivider>Scene Plan</NDivider>
                <NDataTable
                  :columns="scenePlanColumns"
                  :data="scenePlanRows"
                  :pagination="{ pageSize: 6 }"
                  size="small"
                />
              </template>

              <NDivider />

              <NSpace wrap align="center">
                <NSelect
                  v-model:value="plansRunId"
                  :options="planRunIdOptions"
                  clearable
                  placeholder="选择 run 加载时间线（含音频轨）"
                  style="width: 320px"
                />
                <NButton :loading="isLoadingRunTimeline" @click="onLoadRunTimeline">
                  加载 Run Timeline
                </NButton>
              </NSpace>

              <NDivider />

              <NSpace wrap align="center">
                <NSelect
                  v-model:value="runCreateChapterId"
                  :options="chapterOptions"
                  clearable
                  placeholder="选择章节用于一键开跑"
                  style="width: 260px"
                />
                <NButton :loading="isCheckingRunGate" @click="onCheckRunGate">Run Gate</NButton>
                <NButton type="primary" :loading="isCreatingRun" @click="onCreateRunFromTranslation">
                  从转译工程创建 Run
                </NButton>
              </NSpace>

              <NAlert v-if="runGateError" type="error">{{ runGateError }}</NAlert>
              <NAlert v-if="runCreateMessage" type="success">{{ runCreateMessage }}</NAlert>

              <template v-if="runGateData">
                <NDescriptions bordered :column="2" size="small" label-placement="top">
                  <NDescriptionsItem label="Gate Ready">{{ runGateData.ready_to_run ? 'yes' : 'no' }}</NDescriptionsItem>
                  <NDescriptionsItem label="Disabled Reason">{{ runGateData.disabled_reason || '-' }}</NDescriptionsItem>
                  <NDescriptionsItem label="Missing">{{ runGateData.missing.length ? runGateData.missing.join(', ') : '-' }}</NDescriptionsItem>
                  <NDescriptionsItem label="Recommended Actions">{{ runGateData.recommended_actions.length ? runGateData.recommended_actions.join(', ') : '-' }}</NDescriptionsItem>
                </NDescriptions>
              </template>

              <NText v-if="planRunIdOptions.length === 0" depth="3" style="font-size:12px">
                当前暂无可选 run。请先点击上方「加载章节 Plans」，系统会生成 preview run 并自动选中。
              </NText>

              <NAlert v-if="runTimelineError" type="error">{{ runTimelineError }}</NAlert>

              <template v-if="runTimelineData">
                <NDescriptions bordered :column="3" size="small" label-placement="top">
                  <NDescriptionsItem label="Run ID">{{ runTimelineData.run_id }}</NDescriptionsItem>
                  <NDescriptionsItem label="总时长(ms)">{{ runTimelineData.total_duration_ms }}</NDescriptionsItem>
                  <NDescriptionsItem label="视频/音频/特效轨">
                    {{ runTimelineData.video_tracks.length }}/{{ runTimelineData.audio_tracks.length }}/{{ runTimelineData.effect_tracks.length }}
                  </NDescriptionsItem>
                </NDescriptions>

                <NText depth="3" style="font-size:12px">
                  该时间线可用于 NLE 装配（对白对齐镜头段，BGM/ambience 铺底，SFX 插点）。
                </NText>
                <pre class="json-panel">{{ JSON.stringify(runTimelineData, null, 2) }}</pre>
              </template>
            </NSpace>
          </NCard>
        </NTabPane>

        <!-- ════ Tab 4: 一致性中心 ════ -->
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

        <!-- ════ Tab 5: 术语词典 ════ -->
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
  NEmpty,
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
  deleteTranslationBlock,
  executeTranslationPlan,
  batchDeleteTranslationJobs,
  batchRetryTranslationJobs,
  cancelTranslationJob,
  deleteTranslationJob,
  listConsistencyWarnings,
  listEntityVariants,
  listTranslationPlanItems,
  listProviders,
  previewChapterPlan,
  getRunTimeline,
  gateTranslationProjectRun,
  createRunFromTranslationProject,
  listScriptBlocks,
  lockEntityVariant,
  resolveWarning,
  segmentChapters,
  translateBlocks,
  updateTranslationBlock,
  updateTranslationProject,
  type ConsistencyWarningResponse,
  type EntityNameVariantResponse,
  type TranslationPlanItemResponse,
  type ScriptBlockResponse,
  type TranslationProjectResponse,
  type ChapterPreviewResponse,
  type TranslationRunGateResponse,
  type TimelinePlan,
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
const selectedChapterIds = ref<string[]>([]);

// Segment / Translate
const isSegmenting = ref(false);
const isTranslating = ref(false);
const isExecutingPlan = ref(false);
const isCleaningJobs = ref(false);
const planItems = ref<TranslationPlanItemResponse[]>([]);
const selectedPlanItemIds = ref<string[]>([]);

// Plans (read-only aggregate)
const plansChapterId = ref<string | null>(null);
const isLoadingPreviewPlan = ref(false);
const previewPlanError = ref("");
const previewPlanData = ref<ChapterPreviewResponse | null>(null);
const plansRunId = ref<string | null>(null);
const isLoadingRunTimeline = ref(false);
const runTimelineError = ref("");
const runTimelineData = ref<TimelinePlan | null>(null);
const runCreateChapterId = ref<string | null>(null);
const isCheckingRunGate = ref(false);
const isCreatingRun = ref(false);
const runGateError = ref("");
const runCreateMessage = ref("");
const runGateData = ref<TranslationRunGateResponse | null>(null);

// Script blocks tab
const scriptChapterId = ref<string | null>(null);
const scriptBlocks = ref<ScriptBlockResponse[]>([]);
const isSavingBlocks = ref(false);
const blockEdits = ref<Record<string, { translated_text: string; status: string }>>({});
const blockSaveMessage = ref("");
const blockError = ref("");
const blockTypeFilter = ref<string | null>("");
const retranslateProviderId = ref<string | null>(null);
const executionProviderId = ref<string | null>(null);
const deletingBlockId = ref<string | null>(null);
const retranslatingBlockId = ref<string | null>(null);
const providerOptions = ref<{ label: string; value: string }[]>([]);

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

const blockTypeFilterOptions = [
  { label: "全部", value: "" },
  { label: "叙述", value: "narration" },
  { label: "对白", value: "dialogue" },
  { label: "动作", value: "action" },
  { label: "标题", value: "heading" },
  { label: "场景分隔", value: "scene_break" },
];

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

const planStats = computed(() => {
  const total = planItems.value.length;
  const pending = planItems.value.filter(i => i.item_status === "pending").length;
  const running = planItems.value.filter(i => i.item_status === "running").length;
  const failed = planItems.value.filter(i => i.item_status === "failed").length;
  const succeeded = planItems.value.filter(i => i.item_status === "succeeded").length;
  return { total, pending, running, failed, succeeded };
});

const planRunIdOptions = computed(() => {
  const runIds = new Set<string>();
  for (const item of planItems.value) {
    if (item.last_run_id) {
      runIds.add(item.last_run_id);
    }
  }
  if (previewPlanData.value?.preview_run_id) {
    runIds.add(previewPlanData.value.preview_run_id);
  }
  const uniqueRunIds = Array.from(runIds);
  return uniqueRunIds.map((id) => ({ label: id, value: id }));
});

const shotPlanRows = computed(() =>
  (previewPlanData.value?.shot_plan ?? []).map((item, idx) => ({
    idx: idx + 1,
    shot_type: pickString(item, ["shot_type", "type"]),
    description: pickString(item, ["shot_goal", "description", "prompt", "title"]),
    duration: pickDuration(item),
    raw: item,
  })),
);

const scenePlanRows = computed(() =>
  (previewPlanData.value?.scene_plan ?? []).map((item, idx) => ({
    idx: idx + 1,
    location: pickString(item, ["scene_location_hint", "location", "place", "scene_label"]),
    mood: pickString(item, ["emotion_tone", "mood", "tone", "atmosphere"]),
    summary: pickString(item, ["scene_goal", "summary", "description", "goal"]),
    raw: item,
  })),
);

const filteredBlocks = computed(() => {
  if (!blockTypeFilter.value) return scriptBlocks.value;
  return scriptBlocks.value.filter(b => b.block_type === blockTypeFilter.value);
});
const effectiveModelProviderId = computed<string | null>(() =>
  executionProviderId.value || project.value?.model_provider_id || providerOptions.value[0]?.value || null
);

// ─── Helpers ──────────────────────────────────────────────────────────────────
function statusType(status: string): "default" | "info" | "success" | "warning" | "error" {
  return STATUS_TYPE_MAP[status] ?? "default";
}

function blockTypeTag(blockType: string): "default" | "info" | "success" | "warning" | "error" {
  return { narration: "default", dialogue: "info", action: "warning", heading: "success", scene_break: "error" }[blockType] as any ?? "default";
}

function stringifyError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function pickString(item: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = item[key];
    if (typeof value === "string" && value.trim().length > 0) {
      return value;
    }
  }
  return "-";
}

function pickNumber(item: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = item[key];
    if (typeof value === "number" && Number.isFinite(value)) {
      return String(value);
    }
  }
  return "-";
}

function pickDuration(item: Record<string, unknown>): string {
  const durationMs = item["provisional_duration_ms"];
  if (typeof durationMs === "number" && Number.isFinite(durationMs)) {
    return `${Math.round(durationMs / 100) / 10}s`;
  }
  const durationSec = item["duration_sec"];
  if (typeof durationSec === "number" && Number.isFinite(durationSec)) {
    return `${durationSec}s`;
  }
  const legacyDurationMs = item["duration_ms"];
  if (typeof legacyDurationMs === "number" && Number.isFinite(legacyDurationMs)) {
    return `${Math.round(legacyDurationMs / 100) / 10}s`;
  }
  return "-";
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
    if (!executionProviderId.value && data.model_provider_id) {
      executionProviderId.value = data.model_provider_id;
    }

    // Load novel chapters
    const chaptersResp = await http.get<{ id: string; chapter_no: number; title: string | null }[]>(
      `/api/v1/novels/${data.novel_id}/chapters`
    );
    chapters.value = chaptersResp.data.map(c => ({
      label: `第${c.chapter_no}章 ${c.title ?? ""}`.trim(),
      value: c.id,
    }));
    if (selectedChapterIds.value.length === 0) {
      selectedChapterIds.value = chapters.value.map((c) => c.value);
    }
    if (!plansChapterId.value && chapters.value.length > 0) {
      plansChapterId.value = chapters.value[0].value;
    }
    if (!runCreateChapterId.value && chapters.value.length > 0) {
      runCreateChapterId.value = chapters.value[0].value;
    }

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
    await onLoadPlanItems();
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

async function onLoadPlanItems(): Promise<void> {
  try {
    planItems.value = await listTranslationPlanItems(props.projectId);
    if (!plansRunId.value) {
      const firstRunId = planItems.value.find((item) => item.last_run_id)?.last_run_id ?? null;
      plansRunId.value = firstRunId;
    }
  } catch (error) {
    opError.value = `加载计划失败: ${stringifyError(error)}`;
  }
}

async function onLoadPreviewPlan(): Promise<void> {
  previewPlanError.value = "";
  if (!plansChapterId.value) {
    previewPlanError.value = "请先选择章节";
    return;
  }
  isLoadingPreviewPlan.value = true;
  try {
    previewPlanData.value = await previewChapterPlan(plansChapterId.value, {
      tenant_id: "default",
      project_id: "default",
      target_output_language: project.value?.target_language_code,
    });
    if (previewPlanData.value.preview_run_id) {
      plansRunId.value = previewPlanData.value.preview_run_id;
    }
  } catch (error) {
    previewPlanError.value = `加载章节 Plans 失败: ${stringifyError(error)}`;
  } finally {
    isLoadingPreviewPlan.value = false;
  }
}

async function onLoadRunTimeline(): Promise<void> {
  runTimelineError.value = "";
  if (!plansRunId.value) {
    runTimelineError.value = "请先选择 run";
    return;
  }
  isLoadingRunTimeline.value = true;
  try {
    runTimelineData.value = await getRunTimeline(plansRunId.value);
  } catch (error) {
    runTimelineError.value = `加载 Run Timeline 失败: ${stringifyError(error)}`;
  } finally {
    isLoadingRunTimeline.value = false;
  }
}

async function onCheckRunGate(): Promise<void> {
  runGateError.value = "";
  runCreateMessage.value = "";
  isCheckingRunGate.value = true;
  try {
    runGateData.value = await gateTranslationProjectRun(props.projectId, {
      chapter_id: runCreateChapterId.value ?? undefined,
    });
  } catch (error) {
    runGateError.value = `Run Gate 检查失败: ${stringifyError(error)}`;
  } finally {
    isCheckingRunGate.value = false;
  }
}

async function onCreateRunFromTranslation(): Promise<void> {
  runGateError.value = "";
  runCreateMessage.value = "";
  isCreatingRun.value = true;
  try {
    const response = await createRunFromTranslationProject(props.projectId, {
      chapter_id: runCreateChapterId.value ?? undefined,
      requested_quality: "standard",
      language_context: project.value?.target_language_code ?? undefined,
      use_cache: true,
      force_rerun: false,
    });
    runGateData.value = response.gate;
    if (response.run_id) {
      plansRunId.value = response.run_id;
      runCreateMessage.value = `Run 已创建：${response.run_id}`;
    } else {
      runCreateMessage.value = response.message ?? "当前依赖未满足，已返回 Gate 结果";
    }
  } catch (error) {
    runGateError.value = `创建 Run 失败: ${stringifyError(error)}`;
  } finally {
    isCreatingRun.value = false;
  }
}

// ─── Operations ───────────────────────────────────────────────────────────────
function onSelectAllChapters(): void {
  selectedChapterIds.value = chapterOptions.value.map((c) => c.value);
}

async function onExecutePlan(mode: "pending" | "failed" | "selected" | "untranslated"): Promise<void> {
  clearOp();
  const providerId = effectiveModelProviderId.value;
  if (!providerId) {
    opError.value = "请先选择执行 Provider";
    return;
  }
  isExecutingPlan.value = true;
  try {
    const selectedByChapter =
      mode === "selected"
        ? planItems.value
            .filter((i) => i.chapter_id && selectedChapterIds.value.includes(i.chapter_id))
            .map((i) => i.id)
        : [];
    const payload = {
      batch_size: project.value?.batch_size ?? 10,
      only_pending: mode === "pending",
      only_failed: mode === "failed",
      only_untranslated: mode === "untranslated",
      selected_item_ids: mode === "selected" ? (selectedPlanItemIds.value.length ? selectedPlanItemIds.value : selectedByChapter) : [],
      model_provider_id: providerId,
    };
    const result = await executeTranslationPlan(props.projectId, payload);
    opMessage.value = `计划执行完成：执行 ${result.executed}，成功 ${result.succeeded}，失败 ${result.failed}，告警 ${result.warnings}`;
    await Promise.all([onLoadPlanItems(), onLoadAllBlocks(), onLoadWarnings(), onLoadVariants()]);
  } catch (error) {
    opError.value = `计划执行失败: ${stringifyError(error)}`;
  } finally {
    isExecutingPlan.value = false;
  }
}

function onUpdateSelectedPlanItemIds(keys: Array<string | number>): void {
  selectedPlanItemIds.value = keys.map(String);
}

function isDeletableJobStatus(status: string): boolean {
  return status === "failed" || status === "skipped" || status === "canceled" || status === "stale";
}

async function onDeletePlanItem(row: TranslationPlanItemResponse): Promise<void> {
  clearOp();
  isCleaningJobs.value = true;
  try {
    if (row.item_status === "running") {
      await cancelTranslationJob(row.id);
      opMessage.value = "运行中任务已取消（标记为 skipped）";
    } else {
      await deleteTranslationJob(row.id);
      opMessage.value = "任务已删除";
    }
    await onLoadPlanItems();
  } catch (error) {
    opError.value = `任务操作失败: ${stringifyError(error)}`;
  } finally {
    isCleaningJobs.value = false;
  }
}

async function onBatchRetryFailedJobs(): Promise<void> {
  clearOp();
  isCleaningJobs.value = true;
  try {
    const ids =
      selectedPlanItemIds.value.length > 0
        ? selectedPlanItemIds.value
        : planItems.value.filter((i) => isDeletableJobStatus(i.item_status)).map((i) => i.id);
    const result = await batchRetryTranslationJobs({ job_ids: ids });
    opMessage.value = `批量重试完成：${result.retried} 条，跳过 ${result.skipped} 条`;
    await onLoadPlanItems();
  } catch (error) {
    opError.value = `批量重试失败: ${stringifyError(error)}`;
  } finally {
    isCleaningJobs.value = false;
  }
}

async function onBatchDeleteFailedJobs(): Promise<void> {
  clearOp();
  isCleaningJobs.value = true;
  try {
    const ids =
      selectedPlanItemIds.value.length > 0
        ? selectedPlanItemIds.value
        : planItems.value.filter((i) => isDeletableJobStatus(i.item_status)).map((i) => i.id);
    const result = await batchDeleteTranslationJobs({ job_ids: ids });
    opMessage.value = `批量删除完成：${result.deleted} 条，跳过 ${result.skipped} 条`;
    selectedPlanItemIds.value = [];
    await onLoadPlanItems();
  } catch (error) {
    opError.value = `批量删除失败: ${stringifyError(error)}`;
  } finally {
    isCleaningJobs.value = false;
  }
}

async function onSegment(): Promise<void> {
  clearOp();
  if (selectedChapterIds.value.length === 0) {
    opError.value = "请先选择至少一个文章任务（章节）";
    return;
  }
  isSegmenting.value = true;
  try {
    let totalCreated = 0;
    for (const chapterId of selectedChapterIds.value) {
      const result = await segmentChapters(props.projectId, {
        chapter_id: chapterId,
      });
      totalCreated += result.blocks_created;
    }
    opMessage.value = `分块完成：${selectedChapterIds.value.length} 个文章任务，共创建 ${totalCreated} 个块`;
    await onLoadAllBlocks();
  } catch (error) {
    opError.value = `分块失败: ${stringifyError(error)}`;
  } finally {
    isSegmenting.value = false;
  }
}

async function onTranslate(): Promise<void> {
  clearOp();
  const providerId = effectiveModelProviderId.value;
  if (!providerId) {
    opError.value = "请先选择执行 Provider";
    return;
  }
  if (selectedChapterIds.value.length === 0) {
    opError.value = "请先选择至少一个文章任务（章节）";
    return;
  }
  isTranslating.value = true;
  try {
    let totalTranslated = 0;
    let totalWarnings = 0;
    for (const chapterId of selectedChapterIds.value) {
      const result = await translateBlocks(props.projectId, {
        chapter_id: chapterId,
        model_provider_id: providerId,
        batch_size: 10,
      });
      totalTranslated += result.translated;
      totalWarnings += result.warnings;
    }
    opMessage.value = `翻译完成：${selectedChapterIds.value.length} 个文章任务，${totalTranslated} 块，${totalWarnings} 条告警`;
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

async function onLoadProviders(): Promise<void> {
  try {
    const list = await listProviders("default", "default");
    providerOptions.value = list.map((p: any) => ({ label: p.name ?? p.id, value: p.id }));
    if (!executionProviderId.value && providerOptions.value.length > 0) {
      executionProviderId.value = providerOptions.value[0].value;
    }
    if (!retranslateProviderId.value && providerOptions.value.length > 0) {
      retranslateProviderId.value = providerOptions.value[0].value;
    }
  } catch {
    // ignore
  }
}

async function onDeleteBlockTranslation(block: ScriptBlockResponse): Promise<void> {
  if (!block.translation) return;
  deletingBlockId.value = block.translation.id;
  blockError.value = "";
  try {
    await deleteTranslationBlock(props.projectId, block.translation.id);
    // Reload to reflect deletion
    await onLoadBlocks();
    blockSaveMessage.value = "译文已删除，可重新翻译";
  } catch (error) {
    blockError.value = `删除失败: ${stringifyError(error)}`;
  } finally {
    deletingBlockId.value = null;
  }
}

async function onRetranslateBlock(block: ScriptBlockResponse): Promise<void> {
  retranslatingBlockId.value = block.id;
  blockError.value = "";
  try {
    await translateBlocks(props.projectId, {
      script_block_ids: [block.id],
      model_provider_id: retranslateProviderId.value ?? undefined,
      batch_size: 1,
    });
    await onLoadBlocks();
    blockSaveMessage.value = "重新翻译完成";
  } catch (error) {
    blockError.value = `重新翻译失败: ${stringifyError(error)}`;
  } finally {
    retranslatingBlockId.value = null;
  }
}

async function onSaveBlock(block: ScriptBlockResponse): Promise<void> {
  if (!block.translation) return;
  const edit = blockEdits.value[block.id];
  if (!edit) return;
  blockError.value = "";
  try {
    await updateTranslationBlock(props.projectId, block.translation.id, {
      translated_text: edit.translated_text,
      status: edit.status,
    });
    blockSaveMessage.value = "已保存";
    await onLoadBlocks();
  } catch (error) {
    blockError.value = `保存失败: ${stringifyError(error)}`;
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

const planColumns: DataTableColumns<TranslationPlanItemResponse> = [
  {
    type: "selection",
    width: 40,
  },
  {
    title: "序号",
    key: "order_no",
    width: 70,
    render: (row) => row.order_no + 1,
  },
  {
    title: "章节",
    key: "chapter_id",
    render: (row) => {
      const chapter = chapters.value.find((c) => c.value === row.chapter_id);
      return chapter?.label ?? row.chapter_id ?? "—";
    },
  },
  {
    title: "状态",
    key: "item_status",
    width: 110,
    render: (row) => h(NTag, { size: "small", type: statusType(row.item_status) }, {
      default: () => row.item_status,
    }),
  },
  {
    title: "重试",
    key: "retry_count",
    width: 70,
  },
  {
    title: "错误",
    key: "last_error",
    render: (row) => row.last_error ?? "—",
  },
  {
    title: "操作",
    key: "actions",
    width: 100,
    render: (row) =>
      h(NButton, {
        size: "tiny",
        type: row.item_status === "running" ? "warning" : "error",
        ghost: true,
        disabled: row.item_status !== "running" && !isDeletableJobStatus(row.item_status),
        onClick: () => void onDeletePlanItem(row),
      }, {
        default: () => (row.item_status === "running" ? "取消" : (isDeletableJobStatus(row.item_status) ? "删除" : "跳过")),
      }),
  },
];

const shotPlanColumns: DataTableColumns<Record<string, unknown>> = [
  { title: "#", key: "idx", width: 50 },
  { title: "镜头类型", key: "shot_type", width: 100 },
  { title: "描述", key: "description" },
  { title: "时长", key: "duration", width: 80 },
];

const scenePlanColumns: DataTableColumns<Record<string, unknown>> = [
  { title: "#", key: "idx", width: 50 },
  { title: "地点", key: "location", width: 140 },
  { title: "氛围", key: "mood", width: 120 },
  { title: "摘要", key: "summary" },
];

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
  void onLoadProviders();
  void onLoadPlanItems();
});
</script>

<style scoped>
.page-grid {
  display: flex;
  flex-direction: column;
  gap: 16px;
  padding: 16px;
}

/* Paired source/target block card */
.block-pair {
  border: 1px solid var(--n-border-color, #e0e0e6);
  border-radius: 8px;
  overflow: hidden;
  margin-bottom: 12px;
}

.block-header {
  display: flex;
  align-items: center;
  padding: 6px 10px;
  background: var(--n-color, #f5f5f5);
  border-bottom: 1px solid var(--n-border-color, #e0e0e6);
  font-size: 12px;
  gap: 4px;
}

.source-text {
  padding: 8px 12px;
  background: #f8f8fa;
  color: #555;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  border-bottom: 1px dashed var(--n-border-color, #e0e0e6);
  min-height: 36px;
}

.target-area {
  padding: 6px 8px;
  background: #fff;
  border-bottom: 1px solid var(--n-border-color, #e0e0e6);
  min-height: 44px;
}

.block-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  background: var(--n-color, #fafafa);
}
</style>
