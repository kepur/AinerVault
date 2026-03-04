<template>
  <div class="page-grid">
    <!-- Header -->
    <NCard>
      <NSpace align="center" justify="space-between">
        <NSpace align="center">
          <NIcon size="20" style="color: var(--n-color-primary)">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <path d="M3 5h12M9 3v2m1.048 9.5A18.022 18.022 0 016.412 9m6.088 9h7M11 21l5-10 5 10M12.751 5C11.783 10.77 8.07 15.61 3 18.129"/>
            </svg>
          </NIcon>
          <NText strong style="font-size: 16px">转译工程</NText>
          <NBadge :value="filteredProjects.length" type="info" />
        </NSpace>
        <NButton type="primary" size="small" @click="showCreateModal = true">
          + 新建转译工程
        </NButton>
      </NSpace>
    </NCard>

    <!-- Filter bar -->
    <NCard size="small">
      <NSpace wrap>
        <NSelect
          v-model:value="filterNovelId"
          placeholder="筛选小说"
          clearable
          :options="novelOptions"
          style="width: 200px"
          @update:value="onFilter"
        />
        <NSelect
          v-model:value="filterLangPair"
          placeholder="语言对"
          clearable
          :options="langPairOptions"
          style="width: 180px"
          @update:value="onFilter"
        />
        <NSelect
          v-model:value="filterStatus"
          placeholder="状态"
          clearable
          :options="statusOptions"
          style="width: 140px"
          @update:value="onFilter"
        />
        <NButton @click="onReload" :loading="loading">刷新</NButton>
        <NButton
          type="error"
          ghost
          :loading="deletingProjects"
          @click="onBatchDeleteProjects"
        >
          批量删除失败/归档
        </NButton>
      </NSpace>
    </NCard>

    <NAlert v-if="errorMsg" type="error">{{ errorMsg }}</NAlert>

    <!-- Main content: list + detail panel -->
    <NGrid :cols="3" :x-gap="16">
      <!-- Left: project list (2 cols) -->
      <NGridItem :span="2">
        <NCard title="转译工程列表" :bordered="false" size="small">
          <NDataTable
            :columns="columns"
            :data="filteredProjects"
            :loading="loading"
            :row-key="(r: TranslationProjectResponse) => r.id"
            :checked-row-keys="selectedProjectIds"
            @update:checked-row-keys="onUpdateSelectedProjectIds"
            :row-props="rowProps"
            size="small"
            striped
            :scroll-x="700"
          />
        </NCard>
      </NGridItem>

      <!-- Right: detail panel (1 col) -->
      <NGridItem :span="1">
        <NCard title="工程详情" :bordered="false" size="small" style="min-height: 400px">
          <template v-if="selected">
            <NSpace vertical size="small">
              <NDescriptions :column="1" label-placement="left" bordered size="small">
                <NDescriptionsItem label="ID">
                  <NText code style="font-size: 11px">{{ selected.id }}</NText>
                </NDescriptionsItem>
                <NDescriptionsItem label="小说">{{ novelTitle(selected.novel_id) }}</NDescriptionsItem>
                <NDescriptionsItem label="语言对">
                  {{ selected.source_language_code }} → {{ selected.target_language_code }}
                </NDescriptionsItem>
                <NDescriptionsItem label="状态">
                  <NTag :type="statusType(selected.status)" size="small">{{ statusLabel(selected.status) }}</NTag>
                </NDescriptionsItem>
                <NDescriptionsItem label="一致性模式">{{ selected.consistency_mode }}</NDescriptionsItem>
                <NDescriptionsItem label="粒度/范围">{{ selected.granularity }} / {{ selected.scope_mode }}</NDescriptionsItem>
                <NDescriptionsItem label="创建时间">{{ formatDate(selected.created_at) }}</NDescriptionsItem>
              </NDescriptions>

              <!-- Progress -->
              <NDivider style="margin: 8px 0" />
              <NText strong>翻译进度</NText>
              <NProgress
                type="line"
                :percentage="tpProgress(selected)"
                :status="selected.status === 'completed' ? 'success' : 'default'"
                :show-indicator="true"
              />
              <NGrid :cols="2" :x-gap="8">
                <NGridItem>
                  <NStatistic label="总块数" :value="tpStat(selected, 'total')" />
                </NGridItem>
                <NGridItem>
                  <NStatistic label="已译" :value="tpStat(selected, 'translated')" />
                </NGridItem>
                <NGridItem>
                  <NStatistic label="已审" :value="tpStat(selected, 'reviewed')" />
                </NGridItem>
                <NGridItem>
                  <NStatistic>
                    <template #label>
                      告警
                      <NIcon v-if="tpStat(selected, 'open_warnings') > 0" color="#f0a020" size="14">
                        <svg viewBox="0 0 24 24" fill="currentColor"><path d="M12 2L1 21h22L12 2zm0 3.5L20.5 19h-17L12 5.5zM11 10v4h2v-4h-2zm0 6v2h2v-2h-2z"/></svg>
                      </NIcon>
                    </template>
                    <NText :type="tpStat(selected, 'open_warnings') > 0 ? 'warning' : 'success'">
                      {{ tpStat(selected, 'open_warnings') }}
                    </NText>
                  </NStatistic>
                </NGridItem>
              </NGrid>

              <!-- Glossary preview -->
              <NDivider style="margin: 8px 0" />
              <NSpace align="center" justify="space-between">
                <NText strong>术语表</NText>
                <NText depth="3" style="font-size: 12px">
                  共 {{ glossaryTotal(selected) }} 条
                </NText>
              </NSpace>
              <div v-if="glossaryTotal(selected) > 0">
                <NTag
                  v-for="(val, key) in glossaryPreview(selected)"
                  :key="String(key)"
                  size="small"
                  style="margin: 2px"
                >
                  {{ key }} → {{ val }}
                </NTag>
                <NText v-if="glossaryTotal(selected) > 5" depth="3" style="font-size: 11px">
                  +{{ glossaryTotal(selected) - 5 }} 条
                </NText>
              </div>
              <NText v-else depth="3" style="font-size: 12px">暂无术语表</NText>

              <!-- Open workbench button -->
              <NDivider style="margin: 8px 0" />
              <NAlert type="info" :show-icon="false" style="margin-bottom:8px">
                转译任务按“文章/章节”颗粒度执行，请在工作台选择章节任务后再分块与翻译。
              </NAlert>
              <NButton
                type="primary"
                block
                @click="openWorkbench(selected)"
              >
                打开工作台 →
              </NButton>
            </NSpace>
          </template>
          <template v-else>
            <NEmpty description="点击左侧工程查看详情" style="margin-top: 40px" />
          </template>
        </NCard>
      </NGridItem>
    </NGrid>

    <!-- Create modal -->
    <NModal v-model:show="showCreateModal" title="新建转译工程" preset="card" style="width: 480px">
      <NForm :model="createForm" label-placement="left" label-width="100">
        <NFormItem label="小说">
          <NSelect
            v-model:value="createForm.novel_id"
            :options="novelOptions"
            placeholder="选择小说"
          />
        </NFormItem>
        <NFormItem label="源语言">
          <NSelect
            v-model:value="createForm.source_language_code"
            :options="languageOptions"
          />
        </NFormItem>
        <NFormItem label="目标语言">
          <NSelect
            v-model:value="createForm.target_language_code"
            :options="languageOptions"
          />
        </NFormItem>
        <NFormItem label="一致性模式">
          <NSelect
            v-model:value="createForm.consistency_mode"
            :options="[
              { label: '严格 (strict)', value: 'strict' },
              { label: '均衡 (balanced)', value: 'balanced' },
              { label: '自由 (free)', value: 'free' },
            ]"
          />
        </NFormItem>
        <NDivider style="margin: 6px 0">范围（Scope）</NDivider>
        <NFormItem label="执行粒度">
          <NSelect
            v-model:value="createForm.granularity"
            :options="[
              { label: '章节（chapter）', value: 'chapter' },
              { label: '场景（scene）', value: 'scene' },
              { label: '分段（segment）', value: 'segment' },
            ]"
          />
        </NFormItem>
        <NFormItem label="范围模式">
          <NSelect
            v-model:value="createForm.scope_mode"
            :options="[
              { label: '选择章节（chapters_selected）', value: 'chapters_selected' },
              { label: '增量模式（incremental）', value: 'incremental' },
            ]"
          />
        </NFormItem>
        <NFormItem label="章节任务">
          <NSelect
            v-model:value="createForm.scope_chapters"
            multiple
            clearable
            :options="createChapterOptions"
            placeholder="选择要进入执行计划的章节"
          />
        </NFormItem>
        <NDivider style="margin: 6px 0">文化与时空</NDivider>
        <NFormItem label="文化模式">
          <NSelect
            v-model:value="createForm.culture_mode"
            :options="[
              { label: '自动（auto）', value: 'auto' },
              { label: '混合（hybrid）', value: 'hybrid' },
              { label: '手动（manual）', value: 'manual' },
            ]"
          />
        </NFormItem>
        <NFormItem label="时空层开关">
          <NCheckbox v-model:checked="createForm.temporal_enabled">启用 Temporal Layer</NCheckbox>
        </NFormItem>
        <NFormItem label="命名补齐">
          <NCheckbox v-model:checked="createForm.auto_fill_missing_names">缺失目标语言译名时自动补全</NCheckbox>
        </NFormItem>
      </NForm>
      <NAlert v-if="createError" type="error" style="margin-bottom: 12px">{{ createError }}</NAlert>
      <NAlert type="info" style="margin-bottom: 12px">
        创建仅生成翻译计划，不会自动执行整本翻译。
      </NAlert>
      <NSpace justify="end">
        <NButton @click="showCreateModal = false">取消</NButton>
        <NButton type="primary" :loading="creating" @click="onCreateProject">创建</NButton>
      </NSpace>
    </NModal>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, h, watch } from "vue";
import { useRouter } from "vue-router";
import {
  NCard, NGrid, NGridItem, NSpace, NText, NButton, NSelect, NDataTable,
  NTag, NAlert, NEmpty, NDescriptions, NDescriptionsItem, NProgress,
  NStatistic, NDivider, NForm, NFormItem, NModal, NIcon, NBadge, NCheckbox,
  type DataTableColumns,
} from "naive-ui";
import {
  deleteTranslationProject,
  listChapters,
  listNovels,
  listTranslationProjects,
  createTranslationProject,
  type NovelResponse,
  type TranslationProjectResponse,
} from "@/api/product";

const router = useRouter();
const TENANT_ID = "default";
const PROJECT_ID = "default";

// ── State ──────────────────────────────────────────────────────────────────────
const loading = ref(false);
const errorMsg = ref("");
const novels = ref<NovelResponse[]>([]);
const projects = ref<TranslationProjectResponse[]>([]);
const selected = ref<TranslationProjectResponse | null>(null);
const selectedProjectIds = ref<string[]>([]);
const deletingProjects = ref(false);

const filterNovelId = ref<string | null>(null);
const filterLangPair = ref<string | null>(null);
const filterStatus = ref<string | null>(null);

const showCreateModal = ref(false);
const creating = ref(false);
const createError = ref("");
const createChapterOptions = ref<{ label: string; value: string }[]>([]);
const createForm = ref({
  novel_id: "",
  source_language_code: "zh-CN",
  target_language_code: "en-US",
  consistency_mode: "balanced",
  scope_mode: "chapters_selected",
  granularity: "chapter",
  scope_chapters: [] as string[],
  culture_mode: "auto",
  temporal_enabled: false,
  auto_fill_missing_names: false,
});

// ── Options ───────────────────────────────────────────────────────────────────
const novelOptions = computed(() =>
  novels.value.map((n) => ({ label: n.title, value: n.id }))
);

const langPairOptions = computed(() => {
  const pairs = new Set(projects.value.map((p) => `${p.source_language_code} → ${p.target_language_code}`));
  return Array.from(pairs).map((p) => ({ label: p, value: p }));
});

const statusOptions = [
  { label: "草稿", value: "draft" },
  { label: "进行中", value: "in_progress" },
  { label: "失败", value: "failed" },
  { label: "已完成", value: "completed" },
  { label: "已归档", value: "archived" },
  { label: "已取消", value: "canceled" },
  { label: "陈旧", value: "stale" },
];

const languageOptions = [
  { label: "中文 (zh-CN)", value: "zh-CN" },
  { label: "英语 (en-US)", value: "en-US" },
  { label: "英语 (en-GB)", value: "en-GB" },
  { label: "日语 (ja-JP)", value: "ja-JP" },
  { label: "韩语 (ko-KR)", value: "ko-KR" },
  { label: "法语 (fr-FR)", value: "fr-FR" },
  { label: "德语 (de-DE)", value: "de-DE" },
  { label: "西班牙语 (es-ES)", value: "es-ES" },
  { label: "阿拉伯语 (ar-SA)", value: "ar-SA" },
];

// ── Filtered projects ─────────────────────────────────────────────────────────
const filteredProjects = computed(() => {
  let list = projects.value;
  if (filterNovelId.value) {
    list = list.filter((p) => p.novel_id === filterNovelId.value);
  }
  if (filterLangPair.value) {
    list = list.filter(
      (p) => `${p.source_language_code} → ${p.target_language_code}` === filterLangPair.value
    );
  }
  if (filterStatus.value) {
    list = list.filter((p) => p.status === filterStatus.value);
  }
  return list;
});

// ── Helpers ───────────────────────────────────────────────────────────────────
function novelTitle(novelId: string) {
  return novels.value.find((n) => n.id === novelId)?.title ?? novelId;
}

function tpStat(p: TranslationProjectResponse, key: string): number {
  return Number((p.stats_json as Record<string, unknown>)?.[key] ?? 0);
}

function tpProgress(p: TranslationProjectResponse): number {
  const total = tpStat(p, "total");
  if (total === 0) return 0;
  return Math.round((tpStat(p, "translated") / total) * 100);
}

function glossaryTotal(p: TranslationProjectResponse): number {
  return Object.keys(p.term_dictionary_json ?? {}).length;
}

function glossaryPreview(p: TranslationProjectResponse): Record<string, string> {
  const entries = Object.entries(p.term_dictionary_json ?? {}).slice(0, 5);
  return Object.fromEntries(entries);
}

function statusLabel(status: string) {
  return { draft: "草稿", in_progress: "进行中", failed: "失败", completed: "已完成", archived: "已归档", canceled: "已取消", stale: "陈旧" }[status] ?? status;
}

function statusType(status: string): "default" | "info" | "success" | "warning" | "error" {
  return { draft: "default", in_progress: "info", failed: "error", completed: "success", archived: "warning", canceled: "warning", stale: "warning" }[status] as any ?? "default";
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleString("zh-CN", { dateStyle: "short", timeStyle: "short" });
}

// ── Table columns ─────────────────────────────────────────────────────────────
const columns: DataTableColumns<TranslationProjectResponse> = [
  {
    type: "selection",
    width: 40,
  },
  {
    title: "小说",
    key: "novel_id",
    width: 140,
    ellipsis: { tooltip: true },
    render: (row) => novelTitle(row.novel_id),
  },
  {
    title: "语言对",
    key: "lang_pair",
    width: 140,
    render: (row) => h("span", {}, `${row.source_language_code} → ${row.target_language_code}`),
  },
  {
    title: "粒度/范围",
    key: "scope",
    width: 140,
    render: (row) => h("span", {}, `${row.granularity}/${row.scope_mode}`),
  },
  {
    title: "状态",
    key: "status",
    width: 90,
    render: (row) =>
      h(NTag, { type: statusType(row.status), size: "small" }, { default: () => statusLabel(row.status) }),
  },
  {
    title: "进度",
    key: "progress",
    width: 100,
    render: (row) =>
      h(NProgress, {
        type: "line",
        percentage: tpProgress(row),
        showIndicator: true,
        style: "min-width: 80px",
      }),
  },
  {
    title: "块数",
    key: "total",
    width: 60,
    render: (row) => tpStat(row, "total"),
  },
  {
    title: "告警",
    key: "warnings",
    width: 60,
    render: (row) => {
      const count = tpStat(row, "open_warnings");
      return h(NTag, { type: count > 0 ? "warning" : "success", size: "small" }, { default: () => count });
    },
  },
  {
    title: "创建时间",
    key: "created_at",
    width: 120,
    ellipsis: true,
    render: (row) => formatDate(row.created_at),
  },
  {
    title: "操作",
    key: "action",
    width: 90,
    render: (row) =>
      h(
        NButton,
        {
          size: "tiny",
          type: "error",
          ghost: true,
          disabled: !isProjectDeletable(row.status),
          loading: deletingProjects.value && selectedProjectIds.value.includes(row.id),
          onClick: () => void onDeleteProject(row),
        },
        { default: () => "删除" },
      ),
  },
];

// ── Row interaction ────────────────────────────────────────────────────────────
function rowProps(row: TranslationProjectResponse) {
  return {
    style: { cursor: "pointer", background: selected.value?.id === row.id ? "var(--n-color-hover)" : "" },
    onClick: () => {
      selected.value = row;
    },
  };
}

// ── Data loading ──────────────────────────────────────────────────────────────
async function onReload() {
  loading.value = true;
  errorMsg.value = "";
  try {
    const [novelList, projectList] = await Promise.all([
      listNovels(TENANT_ID, PROJECT_ID),
      listTranslationProjects({ tenant_id: TENANT_ID, project_id: PROJECT_ID }),
    ]);
    novels.value = novelList;
    projects.value = projectList;
    if (selected.value) {
      selected.value = projects.value.find((p) => p.id === selected.value!.id) ?? null;
    }
  } catch (e: any) {
    errorMsg.value = e?.response?.data?.detail ?? String(e);
  } finally {
    loading.value = false;
  }
}

function onFilter() {
  selected.value = null;
}

function isProjectDeletable(status: string): boolean {
  return status === "failed" || status === "archived" || status === "stale" || status === "canceled";
}

function onUpdateSelectedProjectIds(keys: Array<string | number>): void {
  selectedProjectIds.value = keys.map(String);
}

async function onDeleteProject(row: TranslationProjectResponse): Promise<void> {
  if (!isProjectDeletable(row.status)) return;
  deletingProjects.value = true;
  errorMsg.value = "";
  try {
    await deleteTranslationProject(row.id);
    selectedProjectIds.value = selectedProjectIds.value.filter((id) => id !== row.id);
    await onReload();
  } catch (e: any) {
    errorMsg.value = e?.response?.data?.detail ?? String(e);
  } finally {
    deletingProjects.value = false;
  }
}

async function onBatchDeleteProjects(): Promise<void> {
  const ids =
    selectedProjectIds.value.length > 0
      ? selectedProjectIds.value
      : filteredProjects.value.filter((p) => isProjectDeletable(p.status)).map((p) => p.id);
  if (ids.length === 0) return;
  deletingProjects.value = true;
  errorMsg.value = "";
  try {
    await Promise.all(ids.map((id) => deleteTranslationProject(id)));
    selectedProjectIds.value = [];
    await onReload();
  } catch (e: any) {
    errorMsg.value = e?.response?.data?.detail ?? String(e);
  } finally {
    deletingProjects.value = false;
  }
}

watch(
  () => createForm.value.novel_id,
  async (novelId) => {
    createChapterOptions.value = [];
    createForm.value.scope_chapters = [];
    if (!novelId) return;
    try {
      const chapterList = await listChapters(novelId);
      createChapterOptions.value = chapterList.map((c) => ({
        label: `第${c.chapter_no}章 ${c.title ?? ""}`.trim(),
        value: c.id,
      }));
    } catch {
      // ignore chapter preload failure in create modal
    }
  },
);

// ── Create project ─────────────────────────────────────────────────────────────
async function onCreateProject() {
  if (!createForm.value.novel_id) {
    createError.value = "请选择小说";
    return;
  }
  creating.value = true;
  createError.value = "";
  try {
    await createTranslationProject({
      tenant_id: TENANT_ID,
      project_id: PROJECT_ID,
      novel_id: createForm.value.novel_id,
      source_language_code: createForm.value.source_language_code,
      target_language_code: createForm.value.target_language_code,
      consistency_mode: createForm.value.consistency_mode,
      scope_mode: createForm.value.scope_mode,
      granularity: createForm.value.granularity,
      scope_payload: { chapters: createForm.value.scope_chapters },
      culture_mode: createForm.value.culture_mode,
      temporal_enabled: createForm.value.temporal_enabled,
      auto_fill_missing_names: createForm.value.auto_fill_missing_names,
      naming_policy_by_lang: {
        [createForm.value.target_language_code]: "cultural_equivalent",
      },
    });
    showCreateModal.value = false;
    await onReload();
  } catch (e: any) {
    createError.value = e?.response?.data?.detail ?? String(e);
  } finally {
    creating.value = false;
  }
}

function openWorkbench(p: TranslationProjectResponse) {
  void router.push({ name: "studio-translation-project", params: { projectId: p.id } });
}

onMounted(onReload);
</script>

<style scoped>
.page-grid {
  display: grid;
  gap: 16px;
  padding: 20px;
}
</style>
