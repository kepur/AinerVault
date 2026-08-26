<template>
  <div class="prompt-assets-page">
    <!-- ── Header ── -->
    <NCard size="small">
      <template #header>
        <NSpace align="center" :size="8">
          <span style="font-size: 16px; font-weight: 600;">素材提示词库 & 角色成长</span>
          <NTag v-if="assets.length" size="small" :bordered="false" type="info">
            {{ assets.length }} 个素材
          </NTag>
        </NSpace>
      </template>
      <template #header-extra>
        <NSpace :size="8" align="center">
          <NSelect
            v-model:value="selectedNovelId"
            :options="novelOptions"
            placeholder="选择小说"
            filterable
            clearable
            style="width: 200px;"
            @update:value="onNovelChange"
          />
          <NSelect
            v-model:value="filterType"
            :options="assetTypeOptions"
            placeholder="全部类型"
            clearable
            style="width: 150px;"
          />
          <NButton :loading="loading" :disabled="!selectedNovelId" @click="reload" secondary size="small">
            刷新
          </NButton>
          <NButton type="primary" :disabled="!selectedNovelId" @click="showCreateDrawer = true">
            新建素材
          </NButton>
        </NSpace>
      </template>
    </NCard>

    <!-- ── Empty ── -->
    <div v-if="!selectedNovelId" style="text-align: center; padding: 60px;">
      <NEmpty description="请先选择一部小说" />
    </div>

    <!-- ── Loading ── -->
    <div v-else-if="loading" style="text-align: center; padding: 40px;">
      <NSpin size="large" />
    </div>

    <!-- ── Tabs ── -->
    <template v-else>
      <NTabs v-model:value="activeTab" type="line" style="margin-top: 8px;">
        <!-- Tab 1: Semantic Assets -->
        <NTabPane name="assets" :tab="`语义素材 (${filteredAssets.length})`">
          <NDataTable
            :columns="assetColumns"
            :data="filteredAssets"
            :bordered="false"
            size="small"
            :max-height="520"
            virtual-scroll
          />
        </NTabPane>

        <!-- Tab 2: Character Stages -->
        <NTabPane name="stages" :tab="`角色阶段 (${stages.length})`">
          <NSpace style="margin-bottom: 8px;" :size="8">
            <NSelect
              v-model:value="stageEntityId"
              :options="entityOptions"
              placeholder="选择角色"
              filterable
              clearable
              style="width: 240px;"
              @update:value="loadStages"
            />
            <NButton type="primary" size="small" :disabled="!stageEntityId" @click="showStageDrawer = true">
              新建阶段
            </NButton>
          </NSpace>
          <NDataTable
            :columns="stageColumns"
            :data="stages"
            :bordered="false"
            size="small"
          />
        </NTabPane>

        <!-- Tab 3: Consistency check -->
        <NTabPane name="consistency" tab="一致性检查">
          <NSpace vertical :size="12">
            <NButton
              type="warning"
              :loading="checkingConsistency"
              :disabled="!selectedNovelId"
              @click="runConsistencyCheck"
            >
              执行一致性检查
            </NButton>
            <NAlert v-if="consistencyResult && consistencyResult.ok" type="success" title="通过">
              全部一致性规则通过，未发现违规项。
            </NAlert>
            <template v-if="consistencyResult && !consistencyResult.ok">
              <NAlert type="warning" :title="`发现 ${consistencyResult.violations.length} 项违规`">
                <div v-for="(v, i) in consistencyResult.violations" :key="i" style="margin-top: 4px;">
                  <NTag :type="v.severity === 'error' ? 'error' : 'warning'" size="small">{{ v.rule_type }}</NTag>
                  <NText style="margin-left: 6px;">{{ v.detail }}</NText>
                </div>
              </NAlert>
            </template>
          </NSpace>
        </NTabPane>
      </NTabs>
    </template>

    <!-- ── Create Asset Drawer ── -->
    <NDrawer v-model:show="showCreateDrawer" :width="480">
      <NDrawerContent title="新建语义素材" closable>
        <NForm label-placement="left" label-width="100px">
          <NFormItem label="类型">
            <NSelect v-model:value="createForm.asset_type" :options="assetTypeOptions" />
          </NFormItem>
          <NFormItem label="标准名称">
            <NInput v-model:value="createForm.canonical_name" placeholder="素材名称" />
          </NFormItem>
          <NFormItem label="关联角色">
            <NSelect v-model:value="createForm.entity_id" :options="entityOptions" clearable placeholder="可选" />
          </NFormItem>
          <NFormItem label="提示词 (JSON)">
            <NInput v-model:value="createForm.prompt_text" type="textarea" :rows="3" placeholder='{"positive":"..."}' />
          </NFormItem>
          <NFormItem label="负面提示词">
            <NInput v-model:value="createForm.negative_text" type="textarea" :rows="2" placeholder='{"negative":"..."}' />
          </NFormItem>
        </NForm>
        <template #footer>
          <NButton type="primary" :loading="creating" @click="onCreateAsset">创建</NButton>
        </template>
      </NDrawerContent>
    </NDrawer>

    <!-- ── Create Stage Drawer ── -->
    <NDrawer v-model:show="showStageDrawer" :width="480">
      <NDrawerContent title="新建角色阶段" closable>
        <NForm label-placement="left" label-width="100px">
          <NFormItem label="阶段名称">
            <NInput v-model:value="stageForm.stage_name" placeholder="如：少年期 / 觉醒后" />
          </NFormItem>
          <NFormItem label="起始章节号">
            <NInputNumber v-model:value="stageForm.chapter_start" :min="1" clearable style="width: 100%;" />
          </NFormItem>
          <NFormItem label="结束章节号">
            <NInputNumber v-model:value="stageForm.chapter_end" :min="1" clearable style="width: 100%;" />
          </NFormItem>
          <NFormItem label="外观覆写 (JSON)">
            <NInput v-model:value="stageForm.appearance_text" type="textarea" :rows="2" placeholder='{"hair":"white"}' />
          </NFormItem>
          <NFormItem label="性格覆写 (JSON)">
            <NInput v-model:value="stageForm.temperament_text" type="textarea" :rows="2" placeholder='{"mood":"dark"}' />
          </NFormItem>
        </NForm>
        <template #footer>
          <NButton type="primary" :loading="creatingStage" @click="onCreateStage">创建</NButton>
        </template>
      </NDrawerContent>
    </NDrawer>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref, reactive } from "vue";
import {
  NAlert,
  NButton,
  NCard,
  NDataTable,
  NDrawer,
  NDrawerContent,
  NEmpty,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NSelect,
  NSpace,
  NSpin,
  NTabPane,
  NTabs,
  NTag,
  NText,
  useMessage,
  type DataTableColumns,
} from "naive-ui";
import {
  listNovels,
  listSemanticAssets,
  createSemanticAsset,
  listCharacterStages,
  createCharacterStage,
  checkPromptAssetConsistency,
  type NovelResponse,
  type SemanticAssetItem,
  type CharacterStageItem,
  type ConsistencyCheckResult,
} from "@/api/product";

const message = useMessage();
const tenantId = "default";
const projectId = "default";

// ── State ──
const loading = ref(false);
const creating = ref(false);
const creatingStage = ref(false);
const checkingConsistency = ref(false);

const selectedNovelId = ref<string | null>(null);
const filterType = ref<string | null>(null);
const activeTab = ref("assets");

const novels = ref<NovelResponse[]>([]);
const assets = ref<SemanticAssetItem[]>([]);
const stages = ref<CharacterStageItem[]>([]);
const stageEntityId = ref<string | null>(null);
const consistencyResult = ref<ConsistencyCheckResult | null>(null);

const showCreateDrawer = ref(false);
const showStageDrawer = ref(false);

const createForm = reactive({
  asset_type: "costume" as string,
  canonical_name: "",
  entity_id: null as string | null,
  prompt_text: "",
  negative_text: "",
});

const stageForm = reactive({
  stage_name: "",
  chapter_start: null as number | null,
  chapter_end: null as number | null,
  appearance_text: "",
  temperament_text: "",
});

// ── Options ──
const assetTypeOptions = [
  { label: "服装 (costume)", value: "costume" },
  { label: "表情 (expression)", value: "expression" },
  { label: "动作 (action)", value: "action" },
  { label: "道具 (prop)", value: "prop" },
  { label: "场景 (scene)", value: "scene" },
  { label: "氛围/镜头 (mood_camera)", value: "mood_camera" },
  { label: "提示词模板 (prompt_template)", value: "prompt_template" },
];

const novelOptions = computed(() =>
  novels.value.map((n) => ({ label: n.title || n.id, value: n.id })),
);

const entityOptions = computed(() => {
  const uniq = new Map<string, string>();
  for (const a of assets.value) {
    if (a.entity_id) {
      uniq.set(a.entity_id, a.entity_id);
    }
  }
  return [...uniq.entries()].map(([id]) => ({ label: id, value: id }));
});

const filteredAssets = computed(() => {
  let list = assets.value;
  if (filterType.value) {
    list = list.filter((a) => a.asset_type === filterType.value);
  }
  return list;
});

// ── Table columns ──
const assetColumns: DataTableColumns<SemanticAssetItem> = [
  { title: "名称", key: "canonical_name", width: 160, ellipsis: { tooltip: true } },
  {
    title: "类型",
    key: "asset_type",
    width: 120,
    render: (row) => h(NTag, { size: "small", bordered: false }, { default: () => row.asset_type }),
  },
  { title: "关联角色", key: "entity_id", width: 200, ellipsis: { tooltip: true } },
  {
    title: "激活",
    key: "is_active",
    width: 60,
    render: (row) =>
      h(NTag, { type: row.is_active ? "success" : "default", size: "tiny" }, { default: () => (row.is_active ? "是" : "否") }),
  },
  { title: "创建时间", key: "created_at", width: 170 },
];

const stageColumns: DataTableColumns<CharacterStageItem> = [
  { title: "阶段名", key: "stage_name", width: 160 },
  { title: "起始章", key: "chapter_start", width: 80 },
  { title: "结束章", key: "chapter_end", width: 80 },
  { title: "默认服装素材", key: "default_costume_asset_id", width: 200, ellipsis: { tooltip: true } },
  { title: "创建时间", key: "created_at", width: 170 },
];

// ── Loaders ──
async function loadNovels() {
  try {
    novels.value = await listNovels(tenantId, projectId);
  } catch (e: any) {
    message.error("加载小说列表失败: " + e.message);
  }
}

async function reload() {
  if (!selectedNovelId.value) return;
  loading.value = true;
  try {
    assets.value = await listSemanticAssets({
      tenant_id: tenantId,
      project_id: projectId,
      novel_id: selectedNovelId.value,
    });
  } catch (e: any) {
    message.error("加载素材失败: " + e.message);
  } finally {
    loading.value = false;
  }
}

async function loadStages(entityId: string | null) {
  if (!entityId) {
    stages.value = [];
    return;
  }
  try {
    stages.value = await listCharacterStages(entityId, {
      tenant_id: tenantId,
      project_id: projectId,
    });
  } catch (e: any) {
    message.error("加载阶段失败: " + e.message);
  }
}

function onNovelChange() {
  assets.value = [];
  stages.value = [];
  consistencyResult.value = null;
  if (selectedNovelId.value) reload();
}

// ── Create asset ──
async function onCreateAsset() {
  if (!selectedNovelId.value || !createForm.canonical_name) {
    message.warning("请填写必填项");
    return;
  }
  creating.value = true;
  try {
    let promptObj = {};
    let negObj = {};
    try { if (createForm.prompt_text) promptObj = JSON.parse(createForm.prompt_text); } catch { /* ignore */ }
    try { if (createForm.negative_text) negObj = JSON.parse(createForm.negative_text); } catch { /* ignore */ }

    await createSemanticAsset({
      tenant_id: tenantId,
      project_id: projectId,
      novel_id: selectedNovelId.value,
      entity_id: createForm.entity_id || undefined,
      asset_type: createForm.asset_type,
      canonical_name: createForm.canonical_name,
      prompt: promptObj,
      negative_prompt: negObj,
    });
    message.success("素材创建成功");
    showCreateDrawer.value = false;
    createForm.canonical_name = "";
    createForm.prompt_text = "";
    createForm.negative_text = "";
    createForm.entity_id = null;
    await reload();
  } catch (e: any) {
    message.error("创建失败: " + e.message);
  } finally {
    creating.value = false;
  }
}

// ── Create stage ──
async function onCreateStage() {
  if (!stageEntityId.value || !stageForm.stage_name) {
    message.warning("请填写必填项");
    return;
  }
  creatingStage.value = true;
  try {
    let appObj = {};
    let tempObj = {};
    try { if (stageForm.appearance_text) appObj = JSON.parse(stageForm.appearance_text); } catch { /* ignore */ }
    try { if (stageForm.temperament_text) tempObj = JSON.parse(stageForm.temperament_text); } catch { /* ignore */ }

    await createCharacterStage(stageEntityId.value, {
      tenant_id: tenantId,
      project_id: projectId,
      stage_name: stageForm.stage_name,
      chapter_start: stageForm.chapter_start ?? undefined,
      chapter_end: stageForm.chapter_end ?? undefined,
      appearance_override: appObj,
      temperament_override: tempObj,
    });
    message.success("阶段创建成功");
    showStageDrawer.value = false;
    stageForm.stage_name = "";
    stageForm.chapter_start = null;
    stageForm.chapter_end = null;
    stageForm.appearance_text = "";
    stageForm.temperament_text = "";
    await loadStages(stageEntityId.value);
  } catch (e: any) {
    message.error("创建失败: " + e.message);
  } finally {
    creatingStage.value = false;
  }
}

// ── Consistency check ──
async function runConsistencyCheck() {
  if (!selectedNovelId.value) return;
  checkingConsistency.value = true;
  try {
    consistencyResult.value = await checkPromptAssetConsistency({
      tenant_id: tenantId,
      project_id: projectId,
      novel_id: selectedNovelId.value,
    });
  } catch (e: any) {
    message.error("一致性检查失败: " + e.message);
  } finally {
    checkingConsistency.value = false;
  }
}

onMounted(loadNovels);
</script>

<style scoped>
.prompt-assets-page {
  max-width: 1300px;
  margin: 0 auto;
  padding: 16px;
}
</style>
