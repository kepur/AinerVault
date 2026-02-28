<template>
  <div class="catalog-page">
    <NCard title="模型目录（Model Catalog）">
      <NText depth="3" style="display:block;margin-bottom:16px">
        按能力分类展示所有已接入模型。绿色「Profile」为精细配置项，橙色「Provider目录」来自厂商 model_catalog 快速导入。
      </NText>
    </NCard>

    <div class="catalog-layout">
      <!-- 左侧：模型分类 -->
      <NCard title="能力分类" size="small" class="category-panel">
        <NMenu
          :value="selectedCategory"
          :options="categoryOptions"
          @update:value="onCategorySelect"
        />
      </NCard>

      <!-- 中间：已接入模型 -->
      <NCard :title="`已接入模型 — ${selectedCategoryLabel} (${filteredModels.length})`" size="small" class="models-panel">
        <NButton size="small" @click="onRefresh" style="margin-bottom:12px">🔄 刷新</NButton>
        <NDataTable
          :columns="modelColumns"
          :data="filteredModels"
          :pagination="{ pageSize: 20 }"
          :bordered="false"
        />
        <NEmpty v-if="filteredModels.length === 0" description="该分类下暂无模型" />
      </NCard>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, h, onMounted, ref } from "vue";
import {
  NButton,
  NCard,
  NDataTable,
  NEmpty,
  NMenu,
  NSpace,
  NTag,
  NText,
  type DataTableColumns,
  type MenuOption,
} from "naive-ui";
import { useI18n } from "@/composables/useI18n";
import { listProviders, listModelProfiles, type ModelProfileResponse, type ProviderResponse } from "@/api/product";

// ─── Categories ────────────────────────────────────────────────────────────────
const CATEGORIES = [
  { key: "all",              label: "全部" },
  { key: "text_generation",  label: "Text LLM（文本生成）" },
  { key: "embedding",        label: "Embedding（向量）" },
  { key: "multimodal",       label: "Multimodal（图文理解）" },
  { key: "image_generation", label: "Image Gen（图片生成）" },
  { key: "video_generation", label: "Video Gen（视频生成）" },
  { key: "tts",              label: "TTS（语音合成）" },
  { key: "stt",              label: "STT（语音识别）" },
  { key: "evaluator",        label: "Evaluator（质量审核）" },
];

// capability_flags key → category key
const CAP_TO_CAT: Record<string, string> = {
  supports_text_generation:  "text_generation",
  supports_embedding:         "embedding",
  supports_multimodal:        "multimodal",
  supports_image_generation:  "image_generation",
  supports_video_generation:  "video_generation",
  supports_tts:               "tts",
  supports_stt:               "stt",
};

// ─── Unified model row type ────────────────────────────────────────────────────
interface UnifiedModel {
  id: string;
  name: string;
  purpose: string;
  capability_tags: string[];
  provider_name: string;
  source: "profile" | "provider_catalog";
}

const { t } = useI18n();
const selectedCategory = ref("all");
const profiles  = ref<ModelProfileResponse[]>([]);
const providers = ref<ProviderResponse[]>([]);

const categoryOptions: MenuOption[] = CATEGORIES.map(c => ({ key: c.key, label: c.label }));

const selectedCategoryLabel = computed(() =>
  CATEGORIES.find(c => c.key === selectedCategory.value)?.label ?? "全部"
);

// ─── Merge ModelProfiles + Provider.model_catalog ─────────────────────────────
const allModels = computed<UnifiedModel[]>(() => {
  const result: UnifiedModel[] = [];
  const seen = new Set<string>();

  // 1. Real ModelProfile records (most precise data)
  for (const p of profiles.value) {
    result.push({
      id: p.id,
      name: p.name,
      purpose: p.purpose ?? "text_generation",
      capability_tags: p.capability_tags ?? [],
      provider_name: (p as any).provider_name ?? p.provider_id ?? "",
      source: "profile",
    });
    seen.add(p.name);
  }

  // 2. Provider.model_catalog entries not yet covered by a Profile
  for (const prov of providers.value) {
    const catalog: string[] = (prov as any).model_catalog ?? [];
    const caps: Record<string, boolean> = (prov as any).capability_flags ?? {};

    // Derive capability_tags array from flags
    const capTags = Object.entries(caps)
      .filter(([, v]) => v)
      .map(([k]) => CAP_TO_CAT[k])
      .filter(Boolean) as string[];

    // Primary purpose = first matching cap
    let purpose = "text_generation";
    if (caps.supports_embedding && !caps.supports_text_generation) purpose = "embedding";
    else if (caps.supports_image_generation && !caps.supports_text_generation) purpose = "image_generation";
    else if (caps.supports_video_generation && !caps.supports_text_generation) purpose = "video_generation";
    else if (caps.supports_tts && !caps.supports_text_generation) purpose = "tts";
    else if (caps.supports_stt && !caps.supports_text_generation) purpose = "stt";

    for (const modelName of catalog) {
      if (seen.has(modelName)) continue;
      result.push({
        id: `${prov.id}::${modelName}`,
        name: modelName,
        purpose,
        capability_tags: capTags,
        provider_name: prov.name,
        source: "provider_catalog",
      });
      seen.add(modelName);
    }
  }

  return result;
});

const filteredModels = computed<UnifiedModel[]>(() => {
  if (selectedCategory.value === "all") return allModels.value;
  return allModels.value.filter(m =>
    m.purpose === selectedCategory.value ||
    m.capability_tags.includes(selectedCategory.value)
  );
});

// ─── Table columns ─────────────────────────────────────────────────────────────
const modelColumns: DataTableColumns<UnifiedModel> = [
  { title: "名称", key: "name" },
  { title: "用途", key: "purpose", width: 160 },
  {
    title: "能力标签",
    key: "capability_tags",
    render: row =>
      h(NSpace, { size: 4 }, {
        default: () => (row.capability_tags || []).map(tag =>
          h(NTag, { size: "small", type: "info" }, { default: () => tag })
        ),
      }),
  },
  { title: "Provider", key: "provider_name", width: 160 },
  {
    title: "来源",
    key: "source",
    width: 130,
    render: row =>
      h(NTag, {
        size: "small",
        type: row.source === "profile" ? "success" : "warning",
      }, { default: () => row.source === "profile" ? "✅ Profile" : "📋 Provider目录" }),
  },
];

function onCategorySelect(key: string): void {
  selectedCategory.value = key;
}

async function onRefresh(): Promise<void> {
  try {
    const [p, m] = await Promise.all([
      listProviders("default", "default"),
      listModelProfiles({ tenant_id: "default", project_id: "default" }),
    ]);
    providers.value = p;
    profiles.value   = m;
  } catch (e) {
    console.error("ModelCatalog load failed", e);
  }
}

onMounted(() => { void onRefresh(); });
</script>

<style scoped>
.catalog-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.catalog-layout {
  display: grid;
  grid-template-columns: 200px 1fr;
  gap: 12px;
}

.category-panel {
  min-height: 400px;
}

.models-panel {
  min-height: 400px;
}

@media (max-width: 1200px) {
  .catalog-layout {
    grid-template-columns: 1fr;
  }
}
</style>
