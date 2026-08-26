<template>
  <div class="entity-prompt-library">
    <!-- ── Header card ── -->
    <NCard size="small">
      <template #header>
        <NSpace align="center" :size="8">
          <span style="font-size: 16px; font-weight: 600;">素材提示词库（基础模型）</span>
          <NTag v-if="stats.total" size="small" :bordered="false" type="info">共 {{ stats.total }} 实体</NTag>
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
            v-model:value="selectedProviderId"
            :options="providerOptions"
            placeholder="选择模型"
            filterable
            clearable
            style="width: 200px;"
          />
          <NSelect
            v-model:value="selectedCulturePackId"
            :options="culturePackOptions"
            placeholder="选择文化包"
            filterable
            style="width: 200px;"
            @update:value="onCulturePackChange"
          />
          <NButton
            :loading="generating"
            :disabled="!selectedNovelId || !selectedProviderId || loading"
            type="warning"
            @click="onGeneratePrompts(false)"
          >
            AI 生成提示词
          </NButton>
          <NPopconfirm @positive-click="onGeneratePrompts(true)">
            <template #trigger>
              <NButton :disabled="!selectedNovelId || !selectedProviderId || loading || generating" quaternary type="error" size="small">
                覆盖重生成
              </NButton>
            </template>
            将使用 AI 覆盖所有已有提示词，确定？
          </NPopconfirm>
          <NButton :loading="loading" :disabled="!selectedNovelId" @click="reload" secondary size="small">刷新</NButton>
          <NButton
            type="primary"
            :loading="batchSaving"
            :disabled="dirtyCount === 0"
            @click="onBatchSave"
          >
            保存 ({{ dirtyCount }})
          </NButton>
          <NButton
            v-if="selectedCulturePackId !== BASE_CULTURE_PACK_VALUE"
            :loading="batchSaving"
            :disabled="!selectedNovelId || loading || allEntities.length === 0"
            secondary
            @click="onCopyBaseToCulturePack"
          >
            从基础版复制
          </NButton>
        </NSpace>
      </template>

      <!-- ── Stats bar ── -->
      <div v-if="stats.total > 0" class="stats-bar">
        <NSpace :size="16">
          <NStatistic label="有提示词" :value="stats.with_prompt" tabular-nums>
            <template #suffix>/ {{ stats.total }}</template>
          </NStatistic>
          <NDivider vertical />
          <template v-for="(cnt, role) in stats.by_role" :key="role">
            <NTag :type="roleTagType(role as string)" size="small" round>
              {{ roleLabel(role as string) }} {{ cnt }}
            </NTag>
          </template>
          <NDivider vertical />
          <template v-for="(cnt, pt) in stats.by_persistence" :key="pt">
            <NTag :type="pt === 'recurring' ? 'warning' : 'default'" size="small" round>
              {{ persistenceLabel(pt as string) }} {{ cnt }}
            </NTag>
          </template>
          <template v-if="selectedCulturePackId !== BASE_CULTURE_PACK_VALUE">
            <NDivider vertical />
            <NTag type="success" size="small" round>
              文化包版 {{ variantCount }}
            </NTag>
            <NTag type="warning" size="small" round>
              继承基础版 {{ inheritedCount }}
            </NTag>
          </template>
        </NSpace>
      </div>
    </NCard>

    <!-- ── Empty state ── -->
    <div v-if="!selectedNovelId" class="empty-hint">
      <NEmpty description="请先在上方选择一部小说" />
    </div>

    <!-- ── Loading ── -->
    <div v-else-if="loading" style="text-align: center; padding: 40px;">
      <NSpin size="large" />
    </div>

    <!-- ── No entities ── -->
    <div v-else-if="allEntities.length === 0" class="empty-hint">
      <NEmpty description="该小说暂无实体，请先在小说详情页执行「实体抽取」" />
    </div>

    <!-- ── Main content ── -->
    <template v-else>
      <!-- ── Filter bar ── -->
      <NCard size="small" style="margin-top: 8px;">
        <NSpace :size="10" align="center">
          <NSelect
            v-model:value="filterType"
            :options="typeOptions"
            placeholder="全部类型"
            clearable
            style="width: 140px;"
            @update:value="() => {}"
          />
          <NSelect
            v-model:value="filterRole"
            :options="roleOptions"
            placeholder="全部角色"
            clearable
            style="width: 140px;"
            @update:value="() => {}"
          />
          <NSelect
            v-model:value="filterPersistence"
            :options="persistenceOptions"
            placeholder="全部持续性"
            clearable
            style="width: 140px;"
            @update:value="() => {}"
          />
          <NSelect
            v-model:value="filterPromptStatus"
            :options="promptStatusOptions"
            placeholder="提示词状态"
            clearable
            style="width: 140px;"
            @update:value="() => {}"
          />
          <NText depth="3" style="font-size: 12px;">
            筛选结果：{{ filteredEntities.length }} 个实体
          </NText>
        </NSpace>
      </NCard>

      <!-- ── Tabs by type ── -->
      <NTabs v-model:value="activeTab" type="line" style="margin-top: 8px;">
        <NTabPane
          v-for="tab in visibleTabs"
          :key="tab.key"
          :name="tab.key"
          :tab="`${tab.label} (${tab.items.length})`"
        >
          <div class="entity-grid">
            <div
              v-for="item in tab.items"
              :key="item.entity_id"
              :class="['entity-card-wrap', dirtySet.has(item.entity_id) ? 'entity-card-wrap--dirty' : '']"
            >
              <!-- Entity card header -->
              <div class="entity-header">
                <NSpace align="center" :size="4" :wrap="false">
                  <NText strong style="font-size: 14px;">{{ item.label }}</NText>
                  <NTag v-if="item.canonical_label && item.canonical_label !== item.label" size="tiny" :bordered="false">
                    {{ item.canonical_label }}
                  </NTag>
                </NSpace>
                <NSpace :size="4" align="center">
                  <!-- Role badge -->
                  <NTag
                    :type="roleTagType(item.role_tag || '')"
                    size="tiny"
                    round
                    :bordered="false"
                    @click="cycleRole(item)"
                    style="cursor: pointer;"
                  >
                    {{ roleLabel(item.role_tag || 'unclassified') }}
                  </NTag>
                  <!-- Persistence badge -->
                  <NTag
                    :type="item.persistence_type === 'recurring' ? 'warning' : 'default'"
                    size="tiny"
                    round
                    :bordered="false"
                    @click="cyclePersistence(item)"
                    style="cursor: pointer;"
                  >
                    {{ persistenceLabel(item.persistence_type || 'unclassified') }}
                  </NTag>
                  <!-- Growth badge -->
                  <NTag
                    v-if="item.growth_type === 'evolving'"
                    type="success"
                    size="tiny"
                    round
                    :bordered="false"
                    @click="cycleGrowth(item)"
                    style="cursor: pointer;"
                  >
                    可成长
                  </NTag>
                  <NTag
                    v-else
                    size="tiny"
                    round
                    :bordered="false"
                    @click="cycleGrowth(item)"
                    style="cursor: pointer;"
                  >
                    静态
                  </NTag>
                  <!-- Chapter count -->
                  <NTag v-if="item.chapter_count > 0" size="tiny" type="info" :bordered="false">
                    {{ item.chapter_count }} 章
                  </NTag>
                  <NTag
                    v-if="selectedCulturePackId && selectedCulturePackId !== BASE_CULTURE_PACK_VALUE"
                    size="tiny"
                    :type="item.prompt_origin === 'variant' ? 'success' : 'warning'"
                    :bordered="false"
                  >
                    {{ item.prompt_origin === 'variant' ? '文化包版' : '继承基础版' }}
                  </NTag>
                </NSpace>
              </div>

              <!-- Aliases -->
              <div v-if="item.alias_list.length > 0" class="entity-aliases">
                <NTag
                  v-for="a in item.alias_list"
                  :key="a"
                  size="tiny"
                  type="info"
                  :bordered="false"
                >{{ a }}</NTag>
              </div>

              <!-- Traits summary (collapsed) -->
              <div v-if="hasTraitsInfo(item)" class="entity-traits">
                <NText depth="3" style="font-size: 11px;">
                  <template v-if="getTraitRole(item)">角色：{{ getTraitRole(item) }}</template>
                  <template v-if="getTraitsList(item).length"> · 特征：{{ getTraitsList(item).join('、') }}</template>
                </NText>
              </div>

              <!-- Anchor prompt editor — structured positive/negative × zh/en -->
              <div class="prompt-struct-editor" style="margin-top: 6px;">
                <NTabs type="segment" size="small" animated>
                  <NTabPane name="zh" tab="中文提示词">
                    <div class="prompt-field">
                      <NText depth="3" style="font-size: 11px;">✅ 正向提示词 (Positive)</NText>
                      <NInput
                        type="textarea"
                        :rows="3"
                        :value="getStructField(item, 'positive_zh')"
                        placeholder="1girl, young woman, long black hair, ..."
                        @update:value="(v: string) => onStructEdit(item, 'positive_zh', v)"
                      />
                    </div>
                    <div class="prompt-field">
                      <NText depth="3" style="font-size: 11px;">❌ 反向提示词 (Negative)</NText>
                      <NInput
                        type="textarea"
                        :rows="2"
                        :value="getStructField(item, 'negative_zh')"
                        placeholder="lowres, bad anatomy, blurry, watermark, ..."
                        @update:value="(v: string) => onStructEdit(item, 'negative_zh', v)"
                      />
                    </div>
                  </NTabPane>
                  <NTabPane name="en" tab="English Prompts">
                    <div class="prompt-field">
                      <NText depth="3" style="font-size: 11px;">✅ Positive Prompt</NText>
                      <NInput
                        type="textarea"
                        :rows="3"
                        :value="getStructField(item, 'positive_en')"
                        placeholder="1girl, young woman, long black hair, ..."
                        @update:value="(v: string) => onStructEdit(item, 'positive_en', v)"
                      />
                    </div>
                    <div class="prompt-field">
                      <NText depth="3" style="font-size: 11px;">❌ Negative Prompt</NText>
                      <NInput
                        type="textarea"
                        :rows="2"
                        :value="getStructField(item, 'negative_en')"
                        placeholder="lowres, bad anatomy, blurry, watermark, ..."
                        @update:value="(v: string) => onStructEdit(item, 'negative_en', v)"
                      />
                    </div>
                  </NTabPane>
                </NTabs>
              </div>

              <!-- Reference images section -->
              <div class="entity-ref-images" style="margin-top: 6px;">
                <div v-if="item.reference_images && item.reference_images.length > 0" class="ref-images-grid">
                  <div v-for="img in item.reference_images" :key="img.id" class="ref-image-item">
                    <NImage :src="img.url" width="80" height="80" object-fit="cover" lazy />
                    <NButton
                      class="ref-image-delete"
                      size="tiny"
                      type="error"
                      quaternary
                      circle
                      @click="onDeleteImage(item, img.id)"
                    >✕</NButton>
                  </div>
                </div>
                <NUpload
                  :show-file-list="false"
                  accept="image/png,image/jpeg,image/webp,image/gif"
                  :custom-request="(opts: any) => handleImageUpload(item, opts.file)"
                >
                  <NButton size="tiny" dashed style="margin-top: 4px;">
                    + 上传参考图
                  </NButton>
                </NUpload>
              </div>

              <!-- Prompt status indicator -->
              <div class="entity-prompt-status">
                <NText v-if="!hasAnyPrompt(item)" type="warning" depth="3" style="font-size: 11px;">
                  ⚠ 未生成提示词
                </NText>
                <NText v-else-if="dirtySet.has(item.entity_id)" type="success" depth="3" style="font-size: 11px;">
                  ● 已修改，待保存
                </NText>
              </div>
            </div>
          </div>
        </NTabPane>
      </NTabs>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from "vue";
import {
  NButton,
  NCard,
  NDivider,
  NEmpty,
  NImage,
  NInput,
  NPopconfirm,
  NSelect,
  NSpace,
  NSpin,
  NStatistic,
  NTabPane,
  NTabs,
  NTag,
  NText,
  NUpload,
  useMessage,
} from "naive-ui";
import {
  listNovels,
  listProviders,
  type BatchAnchorPromptItem,
  getEntityPrompts,
  batchUpdateAnchorPrompts,
  generateEntityPrompts,
  updateEntityClassification,
  uploadEntityReferenceImage,
  deleteEntityReferenceImage,
  listCulturePacks,
  type NovelResponse,
  type EntityPromptItem,
  type PromptStruct,
  type ProviderResponse,
  type CulturePackResponse,
} from "@/api/product";

const message = useMessage();

const tenantId = "default";
const projectId = "default";

const loading = ref(false);
const generating = ref(false);
const batchSaving = ref(false);
const selectedNovelId = ref<string | null>(null);
const selectedProviderId = ref<string | null>(null);
const selectedCulturePackId = ref<string>("__base__");
const filterType = ref<string | null>(null);
const filterRole = ref<string | null>(null);
const filterPersistence = ref<string | null>(null);
const filterPromptStatus = ref<string | null>(null);
const activeTab = ref("person");

const novels = ref<NovelResponse[]>([]);
const providers = ref<ProviderResponse[]>([]);
const culturePacks = ref<CulturePackResponse[]>([]);
const byType = ref<Record<string, EntityPromptItem[]>>({});
const stats = ref<{
  total: number;
  with_prompt: number;
  without_prompt: number;
  by_role: Record<string, number>;
  by_persistence: Record<string, number>;
}>({ total: 0, with_prompt: 0, without_prompt: 0, by_role: {}, by_persistence: {} });

const editBuffer = reactive<Record<string, string>>({});
const structBuffer = reactive<Record<string, PromptStruct>>({});
const dirtySet = reactive(new Set<string>());
const dirtyCount = computed(() => dirtySet.size);
const BASE_CULTURE_PACK_VALUE = "__base__";

const novelOptions = computed(() =>
  novels.value.map((n) => ({ label: n.title, value: n.id })),
);

const providerOptions = computed(() =>
  providers.value
    .filter((p) => p.enabled !== false)
    .map((p) => ({
      label: p.name + (p.model_catalog?.length ? ` (${p.model_catalog[0]})` : ""),
      value: p.id,
    })),
);

const culturePackOptions = computed(() => [
  { label: "基础模型", value: BASE_CULTURE_PACK_VALUE },
  ...culturePacks.value.map((pack) => ({
    label: `${pack.display_name} (${pack.culture_pack_id})`,
    value: pack.culture_pack_id,
  })),
]);

const typeOptions = [
  { label: "角色 (person)", value: "person" },
  { label: "场景 (place)", value: "place" },
  { label: "道具 (item)", value: "item" },
  { label: "组织 (org)", value: "org" },
  { label: "事件 (event)", value: "event" },
  { label: "线索 (clue)", value: "clue" },
  { label: "其他 (other)", value: "other" },
];

const roleOptions = [
  { label: "主角", value: "protagonist" },
  { label: "配角", value: "supporting" },
  { label: "龙套", value: "minor" },
  { label: "背景", value: "background" },
  { label: "关键", value: "key" },
  { label: "未分类", value: "unclassified" },
];

const persistenceOptions = [
  { label: "贯穿型", value: "recurring" },
  { label: "偶发型", value: "episodic" },
  { label: "未分类", value: "unclassified" },
];

const promptStatusOptions = [
  { label: "有提示词", value: "with" },
  { label: "无提示词", value: "without" },
];

// ── Label helpers ──

function roleLabel(role: string): string {
  const m: Record<string, string> = {
    protagonist: "主角",
    supporting: "配角",
    minor: "龙套",
    background: "背景",
    key: "关键",
    unclassified: "未分类",
  };
  return m[role] || role;
}

function roleTagType(role: string): "success" | "warning" | "info" | "error" | "default" {
  const m: Record<string, "success" | "warning" | "info" | "error" | "default"> = {
    protagonist: "error",
    supporting: "warning",
    minor: "info",
    key: "success",
    background: "default",
  };
  return m[role] || "default";
}

function persistenceLabel(pt: string): string {
  const m: Record<string, string> = {
    recurring: "贯穿型",
    episodic: "偶发型",
    unclassified: "未分类",
  };
  return m[pt] || pt;
}

function hasTraitsInfo(item: EntityPromptItem): boolean {
  const tj = item.traits_json || {};
  return !!(tj.role || (tj.traits as string[])?.length);
}

function getTraitRole(item: EntityPromptItem): string {
  return (item.traits_json?.role as string) || "";
}

function getTraitsList(item: EntityPromptItem): string[] {
  return (item.traits_json?.traits as string[]) || [];
}

// ── Computed ──

const allEntities = computed(() => {
  const result: EntityPromptItem[] = [];
  for (const items of Object.values(byType.value)) {
    result.push(...items);
  }
  return result;
});

const inheritedCount = computed(() =>
  allEntities.value.filter((item) => item.prompt_origin === "inherited").length,
);

const variantCount = computed(() =>
  allEntities.value.filter((item) => item.prompt_origin === "variant").length,
);

const filteredEntities = computed(() => {
  return allEntities.value.filter((item) => {
    if (filterType.value && item.type !== filterType.value) return false;
    if (filterRole.value) {
      const r = item.role_tag || "unclassified";
      if (r !== filterRole.value) return false;
    }
    if (filterPersistence.value) {
      const p = item.persistence_type || "unclassified";
      if (p !== filterPersistence.value) return false;
    }
    if (filterPromptStatus.value === "with" && !item.anchor_prompt && !item.prompt_struct?.positive_zh) return false;
    if (filterPromptStatus.value === "without" && (item.anchor_prompt || item.prompt_struct?.positive_zh)) return false;
    return true;
  });
});

const visibleTabs = computed(() => {
  const tabs: { key: string; label: string; items: EntityPromptItem[] }[] = [];
  const labelMap: Record<string, string> = {
    person: "角色", place: "场景", item: "道具",
    org: "组织", event: "事件", clue: "线索",
    skill: "技能", other: "其他",
  };

  // Group filtered entities by type
  const grouped: Record<string, EntityPromptItem[]> = {};
  for (const item of filteredEntities.value) {
    grouped[item.type] = grouped[item.type] || [];
    grouped[item.type].push(item);
  }

  // Sort: recurring + evolving first within each type, then by chapter count desc
  for (const [type, items] of Object.entries(grouped)) {
    if (items.length > 0) {
      items.sort((a, b) => {
        // Priority: protagonist > supporting > minor > background
        const rolePriority: Record<string, number> = { protagonist: 0, supporting: 1, key: 1, minor: 2, background: 3 };
        const ra = rolePriority[a.role_tag || ""] ?? 4;
        const rb = rolePriority[b.role_tag || ""] ?? 4;
        if (ra !== rb) return ra - rb;
        // Then by chapter count desc
        return (b.chapter_count || 0) - (a.chapter_count || 0);
      });
      tabs.push({ key: type, label: labelMap[type] || type, items });
    }
  }

  const order = ["person", "place", "item", "org", "event", "clue", "skill", "other"];
  tabs.sort((a, b) => {
    return (order.indexOf(a.key) === -1 ? 99 : order.indexOf(a.key))
      - (order.indexOf(b.key) === -1 ? 99 : order.indexOf(b.key));
  });
  return tabs;
});

// ── Actions ──

function onEdit(entityId: string, val: string, original: string | null) {
  editBuffer[entityId] = val;
  if (val !== (original ?? "")) {
    dirtySet.add(entityId);
  } else {
    dirtySet.delete(entityId);
  }
}

function getStructField(item: EntityPromptItem, field: keyof PromptStruct): string {
  const buf = structBuffer[item.entity_id];
  if (buf) return buf[field] || "";
  return item.prompt_struct?.[field] || "";
}

function onStructEdit(item: EntityPromptItem, field: keyof PromptStruct, val: string) {
  if (!structBuffer[item.entity_id]) {
    structBuffer[item.entity_id] = {
      positive_zh: item.prompt_struct?.positive_zh || "",
      negative_zh: item.prompt_struct?.negative_zh || "",
      positive_en: item.prompt_struct?.positive_en || "",
      negative_en: item.prompt_struct?.negative_en || "",
    };
  }
  structBuffer[item.entity_id][field] = val;
  // Also sync anchor_prompt from positive_zh for backward compat
  if (field === "positive_zh") {
    editBuffer[item.entity_id] = val;
  }
  dirtySet.add(item.entity_id);
}

function hasAnyPrompt(item: EntityPromptItem): boolean {
  const buf = structBuffer[item.entity_id];
  if (buf) {
    return !!(buf.positive_zh || buf.positive_en);
  }
  return !!(item.anchor_prompt || item.prompt_struct?.positive_zh || item.prompt_struct?.positive_en);
}

async function loadNovels() {
  try {
    const [n, p, packs] = await Promise.all([
      listNovels(tenantId, projectId),
      listProviders(tenantId, projectId),
      listCulturePacks({ tenant_id: tenantId, project_id: projectId }),
    ]);
    novels.value = n;
    providers.value = p;
    culturePacks.value = packs;
    // Auto-select first enabled provider
    if (!selectedProviderId.value && p.length > 0) {
      const first = p.find((x) => x.enabled !== false);
      if (first) selectedProviderId.value = first.id;
    }
  } catch {
    message.error("加载小说/模型/文化包列表失败");
  }
}

async function loadEntities() {
  if (!selectedNovelId.value) return;
  loading.value = true;
  try {
    const res = await getEntityPrompts(selectedNovelId.value, {
      tenant_id: tenantId,
      project_id: projectId,
      culture_pack_id: selectedCulturePackId.value !== BASE_CULTURE_PACK_VALUE ? selectedCulturePackId.value : undefined,
    });
    byType.value = res.by_type;
    stats.value = res.stats;
    // Reset edit state
    for (const key of Object.keys(editBuffer)) delete editBuffer[key];
    for (const key of Object.keys(structBuffer)) delete structBuffer[key];
    dirtySet.clear();
    // Auto-select first non-empty tab
    const first = visibleTabs.value[0];
    if (first) activeTab.value = first.key;
  } catch {
    message.error("加载实体数据失败");
  } finally {
    loading.value = false;
  }
}

function onNovelChange() {
  loadEntities();
}

function onCulturePackChange() {
  loadEntities();
}

function reload() {
  loadNovels();
  if (selectedNovelId.value) loadEntities();
}

async function onGeneratePrompts(overwrite: boolean) {
  if (!selectedNovelId.value || !selectedProviderId.value) {
    message.warning("请先选择小说和模型");
    return;
  }
  generating.value = true;
  try {
    const res = await generateEntityPrompts(selectedNovelId.value, {
      tenant_id: tenantId,
      project_id: projectId,
      model_provider_id: selectedProviderId.value,
      overwrite,
      culture_pack_id: selectedCulturePackId.value !== BASE_CULTURE_PACK_VALUE ? selectedCulturePackId.value : undefined,
    });
    const genMsg = res.generated > 0
      ? `AI 生成 ${res.generated} 个提示词`
      : "提示词已是最新";
    message.success(
      `已分类 ${res.classified} 个实体，${genMsg}` +
      (selectedCulturePackId.value !== BASE_CULTURE_PACK_VALUE ? `（文化包：${selectedCulturePackId.value}）` : "") +
      (res.skipped > 0 ? `，跳过 ${res.skipped} 个` : ""),
    );
    await loadEntities();
  } catch {
    message.error("生成失败，请确认已执行过「世界模型抽离」且模型配置正确");
  } finally {
    generating.value = false;
  }
}

async function onBatchSave() {
  if (!selectedNovelId.value || dirtySet.size === 0) return;
  batchSaving.value = true;
  try {
    const items = Array.from(dirtySet).map((eid) => ({
      entity_id: eid,
      anchor_prompt: editBuffer[eid] ?? structBuffer[eid]?.positive_zh ?? "",
      prompt_struct: structBuffer[eid] || undefined,
    }));
    const res = await batchUpdateAnchorPrompts(selectedNovelId.value, {
      items,
      culture_pack_id: selectedCulturePackId.value !== BASE_CULTURE_PACK_VALUE ? selectedCulturePackId.value : undefined,
    });
    message.success(`已更新 ${res.updated} 个实体提示词`);
    dirtySet.clear();
    await loadEntities();
  } catch {
    message.error("保存失败");
  } finally {
    batchSaving.value = false;
  }
}

async function onCopyBaseToCulturePack() {
  if (!selectedNovelId.value || selectedCulturePackId.value === BASE_CULTURE_PACK_VALUE) return;

  const draftItems: Array<BatchAnchorPromptItem | null> = allEntities.value
    .map((item) => {
      const promptStruct = structBuffer[item.entity_id] || item.prompt_struct;
      const anchorPrompt = editBuffer[item.entity_id]
        ?? promptStruct?.positive_zh
        ?? item.anchor_prompt
        ?? "";
      if (!anchorPrompt && !promptStruct) return null;
      return {
        entity_id: item.entity_id,
        anchor_prompt: anchorPrompt,
        prompt_struct: promptStruct || undefined,
      };
    });
  const items: BatchAnchorPromptItem[] = draftItems.filter((item): item is BatchAnchorPromptItem => item !== null);

  if (items.length === 0) {
    message.warning("当前没有可复制的提示词");
    return;
  }

  batchSaving.value = true;
  try {
    const res = await batchUpdateAnchorPrompts(selectedNovelId.value, {
      items,
      culture_pack_id: selectedCulturePackId.value,
    });
    message.success(`已复制 ${res.updated} 个实体到文化包 ${selectedCulturePackId.value}`);
    dirtySet.clear();
    await loadEntities();
  } catch {
    message.error("复制基础版失败");
  } finally {
    batchSaving.value = false;
  }
}

// ── Classification cycling (click to toggle) ──

const ROLE_CYCLE_PERSON = ["protagonist", "supporting", "minor", "background"];
const ROLE_CYCLE_OTHER = ["key", "background"];
const PERSISTENCE_CYCLE = ["recurring", "episodic"];
const GROWTH_CYCLE = ["evolving", "static"];

type ClassificationField = "role_tag" | "persistence_type" | "growth_type";

async function cycleClassification(item: EntityPromptItem, field: ClassificationField, cycle: string[]) {
  const current = item[field] || cycle[cycle.length - 1];
  const idx = cycle.indexOf(current);
  const next = cycle[(idx + 1) % cycle.length];
  try {
    await updateEntityClassification(item.entity_id, { [field]: next });
    // Update local state
    item[field] = next;
    if (item.traits_json) {
      (item.traits_json as Record<string, unknown>)[field] = next;
    }
  } catch {
    message.error("更新分类失败");
  }
}

function cycleRole(item: EntityPromptItem) {
  const cycle = item.type === "person" ? ROLE_CYCLE_PERSON : ROLE_CYCLE_OTHER;
  cycleClassification(item, "role_tag", cycle);
}

function cyclePersistence(item: EntityPromptItem) {
  cycleClassification(item, "persistence_type", PERSISTENCE_CYCLE);
}

function cycleGrowth(item: EntityPromptItem) {
  cycleClassification(item, "growth_type", GROWTH_CYCLE);
}

// ── Image upload / delete ──

async function handleImageUpload(item: EntityPromptItem, fileInfo: any) {
  const rawFile = fileInfo.file;
  if (!rawFile) return;
  try {
    const res = await uploadEntityReferenceImage(item.entity_id, rawFile);
    item.reference_images = res.reference_images;
    message.success("参考图上传成功");
  } catch {
    message.error("参考图上传失败");
  }
}

async function onDeleteImage(item: EntityPromptItem, imageId: string) {
  try {
    const res = await deleteEntityReferenceImage(item.entity_id, imageId);
    item.reference_images = res.reference_images;
    message.success("参考图已删除");
  } catch {
    message.error("删除参考图失败");
  }
}

onMounted(() => {
  loadNovels();
});
</script>

<style scoped>
.entity-prompt-library {
  padding: 16px;
  max-width: 1500px;
  margin: 0 auto;
}

.stats-bar {
  margin-top: 8px;
  padding: 4px 0;
}

.empty-hint {
  padding: 60px 0;
  text-align: center;
}

.entity-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(400px, 1fr));
  gap: 10px;
  padding: 4px 0;
}

.entity-card-wrap {
  border: 1px solid var(--n-border-color, #e0e0e6);
  border-radius: 8px;
  padding: 12px;
  background: var(--n-color, #fff);
  transition: border-color 0.2s;
}

.entity-card-wrap--dirty {
  border-left: 3px solid #18a058;
}

.entity-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px;
  flex-wrap: wrap;
}

.entity-aliases {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 4px;
}

.entity-traits {
  margin-top: 4px;
  line-height: 1.4;
}

.entity-prompt-status {
  margin-top: 4px;
  min-height: 16px;
}

.prompt-struct-editor :deep(.n-tabs-pane-wrapper) {
  padding-top: 4px;
}

.prompt-field {
  margin-bottom: 6px;
}

.prompt-field > span {
  display: block;
  margin-bottom: 2px;
}

.ref-images-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.ref-image-item {
  position: relative;
  display: inline-block;
  border-radius: 4px;
  overflow: hidden;
  border: 1px solid var(--n-border-color, #e0e0e6);
}

.ref-image-delete {
  position: absolute;
  top: 2px;
  right: 2px;
  width: 18px !important;
  height: 18px !important;
  font-size: 10px;
  opacity: 0.7;
}

.ref-image-item:hover .ref-image-delete {
  opacity: 1;
}
</style>
