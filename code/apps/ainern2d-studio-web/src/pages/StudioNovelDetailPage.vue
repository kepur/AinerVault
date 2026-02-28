<template>
  <div class="page-grid">
    <NCard :title="`小说详情 · ${novelId}`">
      <NSpace>
        <NButton @click="goBack">← 返回列表</NButton>
        <NButton type="primary" @click="onReloadAll">{{ t('common.refresh') }}</NButton>
      </NSpace>
    </NCard>

    <NTabs v-model:value="activeTab" type="card" animated>

      <!-- ═══ Tab 1: 章节管理 ═══ -->
      <NTabPane name="chapters" :tab="t('novels.chapterList')">
        <NCard>
          <NButton @click="showAddChapter = !showAddChapter" style="margin-bottom:12px">
            {{ showAddChapter ? "收起" : "+ 新增章节" }}
          </NButton>

          <template v-if="showAddChapter">
            <NGrid :cols="2" :x-gap="8" :y-gap="8" responsive="screen" item-responsive style="margin-bottom:12px">
              <NGridItem span="0:2 900:1">
                <NFormItem label="章节号"><NInputNumber v-model:value="newChapterNo" :min="1" /></NFormItem>
              </NGridItem>
              <NGridItem span="0:2 900:1">
                <NFormItem label="语言">
                  <NSelect v-model:value="newChapterLanguage" :options="languageOptions" />
                </NFormItem>
              </NGridItem>
              <NGridItem span="0:2">
                <NFormItem label="章节标题"><NInput v-model:value="newChapterTitle" /></NFormItem>
              </NGridItem>
            </NGrid>
            <NFormItem label="章节内容">
              <NInput v-model:value="newChapterContent" type="textarea" :autosize="{ minRows: 4, maxRows: 10 }" />
            </NFormItem>
            <NSpace style="margin-bottom:12px">
              <NButton type="primary" @click="onCreateChapter">创建章节</NButton>
              <NButton @click="showAddChapter = false">{{ t('common.cancel') }}</NButton>
            </NSpace>
          </template>

          <NDataTable :columns="chapterColumns" :data="chapters" :pagination="{ pageSize: 10 }" />
        </NCard>
      </NTabPane>

      <!-- ═══ Tab 2: 影视团队 ═══ -->
      <NTabPane name="team" :tab="t('novels.filmCrew')">
        <NCard>
          <NText depth="3" style="display:block;margin-bottom:16px">
            为本小说每个职位绑定 Persona 实例。团队配置存储在小说的 team_json 字段中。
          </NText>

          <NGrid :cols="2" :x-gap="12" :y-gap="12" responsive="screen" item-responsive>
            <NGridItem v-for="role in TEAM_ROLES" :key="role.key" span="0:2 900:1">
              <NFormItem :label="role.label">
                <NSelect
                  v-model:value="teamBindings[role.key]"
                  :options="personaOptions"
                  :placeholder="`选择${role.label} Persona`"
                  clearable
                  filterable
                  style="flex:1"
                />
              </NFormItem>
            </NGridItem>
          </NGrid>

          <NSpace style="margin-top:8px">
            <NButton type="primary" :loading="isSavingTeam" @click="onSaveTeam">保存团队绑定</NButton>
            <NButton @click="onLoadTeam">重新加载</NButton>
          </NSpace>
          <pre v-if="teamSaveResult" class="json-panel" style="margin-top:12px">{{ teamSaveResult }}</pre>
        </NCard>
      </NTabPane>

      <!-- ═══ Tab 3: 实体抽离 ═══ -->
      <NTabPane name="entities" :tab="t('novels.entityExtract')">
        <NCard>
          <NGrid :cols="3" :x-gap="8" :y-gap="8" responsive="screen" item-responsive>
            <NGridItem span="0:3 900:1">
              <NFormItem label="模型 Provider">
                <NSelect
                  v-model:value="extractProviderId"
                  :options="providerOptions"
                  placeholder="选择 LLM Provider"
                  filterable
                />
              </NFormItem>
            </NGridItem>
            <NGridItem span="0:3 900:1">
              <NFormItem label="目标语言">
                <NSelect v-model:value="extractLanguage" :options="languageOptions" />
              </NFormItem>
            </NGridItem>
            <NGridItem span="0:3 900:1">
              <NFormItem label="文化包（可选）">
                <NInput v-model:value="extractCulturePackId" placeholder="留空则跳过" />
              </NFormItem>
            </NGridItem>
          </NGrid>

          <NButton
            type="primary"
            :loading="isExtracting"
            :disabled="!extractProviderId || isExtracting"
            @click="onExtractEntities"
          >
            {{ isExtracting ? "提取中..." : "一键提取实体" }}
          </NButton>

          <template v-if="extractionResult">
            <NDivider />
            <NGrid :cols="3" :x-gap="12">
              <NGridItem>
                <NStatistic label="实体数" :value="extractionResult.entities_count" />
              </NGridItem>
              <NGridItem>
                <NStatistic label="别名数" :value="extractionResult.aliases_count" />
              </NGridItem>
              <NGridItem>
                <NStatistic label="事件数" :value="extractionResult.events_count" />
              </NGridItem>
            </NGrid>
            <pre class="json-panel" style="margin-top:12px">{{ JSON.stringify(extractionResult.preview, null, 2) }}</pre>
          </template>
        </NCard>
      </NTabPane>

      <!-- ═══ Tab 4: 转译工程 ═══ -->
      <NTabPane name="translation" tab="转译工程">
        <NCard>
          <NSpace vertical>
            <NSpace>
              <NButton type="primary" @click="showCreateTranslation = true">新建转译工程</NButton>
              <NButton @click="onLoadTranslationProjects">{{ t('common.refresh') }}</NButton>
            </NSpace>

            <NDataTable
              :columns="translationColumns"
              :data="translationProjects"
              :pagination="{ pageSize: 10 }"
            />
          </NSpace>

          <!-- 新建工程 Modal -->
          <NModal v-model:show="showCreateTranslation" :title="t('novels.newTranslation')" preset="dialog">
            <NForm label-placement="top">
              <NFormItem label="源语言">
                <NSelect v-model:value="newTpSourceLang" :options="languageOptions" />
              </NFormItem>
              <NFormItem label="目标语言">
                <NSelect v-model:value="newTpTargetLang" :options="languageOptions" />
              </NFormItem>
              <NFormItem label="翻译模型 Provider">
                <NSelect
                  v-model:value="newTpProviderId"
                  :options="providerOptions"
                  clearable
                  filterable
                  placeholder="选择模型 Provider（可选）"
                />
              </NFormItem>
              <NFormItem label="一致性模式">
                <NSelect v-model:value="newTpConsistencyMode" :options="consistencyModeOptions" />
              </NFormItem>
            </NForm>
            <template #action>
              <NSpace>
                <NButton type="primary" :loading="isCreatingTp" @click="onCreateTranslationProject">{{ t('common.create') }}</NButton>
                <NButton @click="showCreateTranslation = false">{{ t('common.cancel') }}</NButton>
              </NSpace>
            </template>
          </NModal>
        </NCard>
      </NTabPane>

    </NTabs>

    <NAlert v-if="message" type="success" :show-icon="true">{{ message }}</NAlert>
    <NAlert v-if="errorMessage" type="error" :show-icon="true">{{ errorMessage }}</NAlert>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import {
  NAlert,
  NButton,
  NCard,
  NDataTable,
  NDivider,
  NForm,
  NFormItem,
  NGrid,
  NGridItem,
  NInput,
  NInputNumber,
  NModal,
  NPopconfirm,
  NSelect,
  NSpace,
  NStatistic,
  NTabPane,
  NTabs,
  NText,
  NTag,
  type DataTableColumns,
} from "naive-ui";
import { useI18n } from "@/composables/useI18n";


import {
  createChapter,
  createTranslationProject,
  deleteChapter,
  extractNovelEntities,
  getNovelTeam,
  listChapters,
  listPersonaPacks,
  listProviders,
  listTranslationProjects,
  setNovelTeam,
  type ChapterResponse,
  type EntityExtractionResponse,
  type NovelTeamMember,
  type PersonaPackResponse,
  type ProviderResponse,
  type TranslationProjectResponse,
} from "@/api/product";

const props = defineProps<{ novelId: string }>();
const { t } = useI18n();

const router = useRouter();

// ─── Constants ────────────────────────────────────────────────────────────────
const TEAM_ROLES = [
  { key: "director",   label: "导演" },
  { key: "art",        label: "美术指导" },
  { key: "photo",      label: "摄影指导" },
  { key: "stunt",      label: "武术指导" },
  { key: "translator", label: "翻译" },
  { key: "voice",      label: "配音导演" },
] as const;

const languageOptions = [
  { label: "简体中文 (zh-CN)", value: "zh-CN" },
  { label: "English (en-US)", value: "en-US" },
  { label: "日本語 (ja-JP)", value: "ja-JP" },
];

const consistencyModeOptions = [
  { label: "平衡 (balanced) — 仅锁定实体报警", value: "balanced" },
  { label: "严格 (strict) — 所有警告必须处理", value: "strict" },
  { label: "自由 (free) — 不校验", value: "free" },
];

// ─── State ────────────────────────────────────────────────────────────────────
const tenantId = ref("default");
const projectId = ref("default");
const activeTab = ref("chapters");

// Chapters
const chapters = ref<ChapterResponse[]>([]);
const showAddChapter = ref(false);
const newChapterNo = ref(1);
const newChapterLanguage = ref("zh-CN");
const newChapterTitle = ref("");
const newChapterContent = ref("");

// Team
const personaPacks = ref<PersonaPackResponse[]>([]);
const isSavingTeam = ref(false);
const teamSaveResult = ref("");
const teamBindings = reactive<Record<string, string | null>>({
  director: null, art: null, photo: null, stunt: null, translator: null, voice: null,
});

// Entities
const providers = ref<ProviderResponse[]>([]);
const extractProviderId = ref<string | null>(null);
const extractLanguage = ref("zh-CN");
const extractCulturePackId = ref("");
const isExtracting = ref(false);
const extractionResult = ref<EntityExtractionResponse | null>(null);

// Translation Projects
const translationProjects = ref<TranslationProjectResponse[]>([]);
const showCreateTranslation = ref(false);
const isCreatingTp = ref(false);
const newTpSourceLang = ref("zh-CN");
const newTpTargetLang = ref("en-US");
const newTpProviderId = ref<string | null>(null);
const newTpConsistencyMode = ref("balanced");

const message = ref("");
const errorMessage = ref("");

// ─── Computed ─────────────────────────────────────────────────────────────────
const personaOptions = computed(() =>
  personaPacks.value.map(p => ({ label: p.name, value: p.id }))
);

const providerOptions = computed(() =>
  providers.value.map(p => ({ label: p.name, value: p.id }))
);

// ─── Chapter columns ──────────────────────────────────────────────────────────
const chapterColumns: DataTableColumns<ChapterResponse> = [
  { title: "章节号", key: "chapter_no", width: 80 },
  { title: "标题", key: "title" },
  { title: "语言", key: "language_code", width: 100 },
  {
    title: "操作",
    key: "action",
    width: 250,
    render: (row) =>
      h(NSpace, { size: 6 }, {
        default: () => [
          h(NButton, {
            size: "tiny",
            type: "primary",
            onClick: () => openChapterEditor(row),
          }, { default: () => "编辑" }),
          h(NButton, {
            size: "tiny",
            type: "info",
            onClick: () => openChapterPreview(row),
          }, { default: () => "预览" }),
          h(NButton, {
            size: "tiny",
            onClick: () => openChapterRevisions(row),
          }, { default: () => "历史" }),
          h(NPopconfirm, {
            onPositiveClick: () => void onDeleteChapter(row.id),
          }, {
            trigger: () => h(NButton, { size: "tiny", type: "error" }, { default: () => "删除" }),
            default: () => "确认删除该章节？",
          }),
        ],
      }),
  },
];

// ─── Translation columns ───────────────────────────────────────────────────────
const STATUS_TYPE_MAP: Record<string, "default" | "info" | "success" | "warning" | "error"> = {
  draft: "default",
  in_progress: "info",
  completed: "success",
  archived: "warning",
};

const translationColumns: DataTableColumns<TranslationProjectResponse> = [
  {
    title: "源语言",
    key: "source_language_code",
    width: 120,
  },
  {
    title: "目标语言",
    key: "target_language_code",
    width: 120,
  },
  {
    title: "状态",
    key: "status",
    width: 110,
    render: (row) =>
      h(NTag, { type: STATUS_TYPE_MAP[row.status] ?? "default", size: "small" }, {
        default: () => row.status,
      }),
  },
  {
    title: "创建时间",
    key: "created_at",
    render: (row) => row.created_at.slice(0, 16).replace("T", " "),
  },
  {
    title: "操作",
    key: "action",
    width: 120,
    render: (row) =>
      h(NButton, {
        size: "small",
        type: "primary",
        onClick: () => openTranslationWorkbench(row.id),
      }, { default: () => "打开工作台" }),
  },
];

// ─── Helpers ──────────────────────────────────────────────────────────────────
function stringifyError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function clearNotice(): void {
  message.value = "";
  errorMessage.value = "";
}

function goBack(): void {
  void router.push({ name: "studio-novels" });
}

function openChapterEditor(chapter: ChapterResponse): void {
  void router.push({
    name: "studio-chapter-editor",
    params: { novelId: props.novelId, chapterId: chapter.id },
  });
}

function openChapterPreview(chapter: ChapterResponse): void {
  void router.push({
    name: "studio-chapter-preview",
    params: { novelId: props.novelId, chapterId: chapter.id },
  });
}

function openChapterRevisions(chapter: ChapterResponse): void {
  void router.push({
    name: "studio-chapter-revisions",
    params: { novelId: props.novelId, chapterId: chapter.id },
  });
}

function openTranslationWorkbench(tpId: string): void {
  void router.push({
    name: "studio-translation-project",
    params: { projectId: tpId },
  });
}

// ─── API Calls ────────────────────────────────────────────────────────────────
async function onReloadAll(): Promise<void> {
  clearNotice();
  try {
    const [chapterList, packs, providerList] = await Promise.all([
      listChapters(props.novelId),
      listPersonaPacks({ tenant_id: tenantId.value, project_id: projectId.value }),
      listProviders(tenantId.value, projectId.value),
    ]);
    chapters.value = chapterList;
    personaPacks.value = packs;
    providers.value = providerList;
    await Promise.all([onLoadTeam(), onLoadTranslationProjects()]);
  } catch (error) {
    errorMessage.value = `reload failed: ${stringifyError(error)}`;
  }
}

async function onLoadTeam(): Promise<void> {
  try {
    const resp = await getNovelTeam(props.novelId, { tenant_id: tenantId.value, project_id: projectId.value });
    for (const key of Object.keys(teamBindings)) {
      teamBindings[key] = resp.team[key]?.persona_pack_id ?? null;
    }
  } catch {
    // team not set yet
  }
}

async function onCreateChapter(): Promise<void> {
  clearNotice();
  try {
    await createChapter(props.novelId, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      chapter_no: newChapterNo.value,
      language_code: newChapterLanguage.value,
      title: newChapterTitle.value || undefined,
      markdown_text: newChapterContent.value,
    });
    chapters.value = await listChapters(props.novelId);
    showAddChapter.value = false;
    newChapterContent.value = "";
    newChapterTitle.value = "";
    message.value = `章节 ${newChapterNo.value} 已创建`;
  } catch (error) {
    errorMessage.value = `create chapter failed: ${stringifyError(error)}`;
  }
}

async function onDeleteChapter(chapterId: string): Promise<void> {
  clearNotice();
  try {
    await deleteChapter(chapterId, { tenant_id: tenantId.value, project_id: projectId.value });
    chapters.value = await listChapters(props.novelId);
    message.value = "章节已删除";
  } catch (error) {
    errorMessage.value = `delete chapter failed: ${stringifyError(error)}`;
  }
}

async function onSaveTeam(): Promise<void> {
  clearNotice();
  isSavingTeam.value = true;
  try {
    const team: Record<string, NovelTeamMember> = {};
    for (const role of TEAM_ROLES) {
      const packId = teamBindings[role.key];
      if (packId) {
        const pack = personaPacks.value.find(p => p.id === packId);
        team[role.key] = { persona_pack_id: packId, persona_pack_name: pack?.name ?? "" };
      }
    }
    const result = await setNovelTeam(props.novelId, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      team,
    });
    teamSaveResult.value = JSON.stringify(result, null, 2);
    message.value = "团队绑定已保存";
  } catch (error) {
    errorMessage.value = `save team failed: ${stringifyError(error)}`;
  } finally {
    isSavingTeam.value = false;
  }
}

async function onLoadTranslationProjects(): Promise<void> {
  try {
    translationProjects.value = await listTranslationProjects({
      novel_id: props.novelId,
      tenant_id: tenantId.value,
      project_id: projectId.value,
    });
  } catch (error) {
    errorMessage.value = `load translation projects failed: ${stringifyError(error)}`;
  }
}

async function onCreateTranslationProject(): Promise<void> {
  clearNotice();
  isCreatingTp.value = true;
  try {
    const tp = await createTranslationProject({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      novel_id: props.novelId,
      source_language_code: newTpSourceLang.value,
      target_language_code: newTpTargetLang.value,
      model_provider_id: newTpProviderId.value,
      consistency_mode: newTpConsistencyMode.value,
    });
    showCreateTranslation.value = false;
    translationProjects.value = await listTranslationProjects({
      novel_id: props.novelId,
      tenant_id: tenantId.value,
      project_id: projectId.value,
    });
    message.value = `转译工程已创建，正在跳转工作台...`;
    void router.push({ name: "studio-translation-project", params: { projectId: tp.id } });
  } catch (error) {
    errorMessage.value = `create translation project failed: ${stringifyError(error)}`;
  } finally {
    isCreatingTp.value = false;
  }
}

async function onExtractEntities(): Promise<void> {
  if (!extractProviderId.value) return;
  clearNotice();
  isExtracting.value = true;
  try {
    extractionResult.value = await extractNovelEntities(props.novelId, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      model_provider_id: extractProviderId.value,
    });
    message.value = `实体提取完成: ${extractionResult.value.entities_count} 个实体`;
  } catch (error) {
    errorMessage.value = `extract failed: ${stringifyError(error)}`;
  } finally {
    isExtracting.value = false;
  }
}

onMounted(() => {
  void onReloadAll();
});
</script>
