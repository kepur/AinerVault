<template>
  <div class="catalog-page">
    <NCard title="模型目录（Model Catalog）">
      <NText depth="3" style="display:block;margin-bottom:16px">
        按能力分类展示所有已接入模型。
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
      <NCard :title="`已接入模型 — ${selectedCategoryLabel}`" size="small" class="models-panel">
        <NButton size="small" @click="onRefresh" style="margin-bottom:12px">🔄 刷新</NButton>
        <NDataTable
          :columns="modelColumns"
          :data="filteredProfiles"
          :pagination="{ pageSize: 20 }"
          :bordered="false"
        />
        <NEmpty v-if="filteredProfiles.length === 0" description="该分类下暂无模型" />
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
  NDivider,
  NEmpty,
  NList,
  NListItem,
  NMenu,
  NSpace,
  NTag,
  NText,
  type DataTableColumns,
  type MenuOption,
} from "naive-ui";
import { useI18n } from "@/composables/useI18n";

import { listProviders, listModelProfiles, type ModelProfileResponse, type ProviderResponse } from "@/api/product";

const CATEGORIES = [
  { key: "all", label: "全部" },
  { key: "text_generation", label: "Text LLM（文本生成）" },
  { key: "embedding", label: "Embedding（向量）" },
  { key: "multimodal", label: "Multimodal（图文理解）" },
  { key: "image_generation", label: "Image Gen（图片生成）" },
  { key: "video_generation", label: "Video Gen（视频生成）" },
  { key: "tts", label: "TTS（语音合成）" },
  { key: "stt", label: "STT（语音识别）" },
  { key: "evaluator", label: "Evaluator（质量审核）" },
];



const { t } = useI18n();

const selectedCategory = ref("all");
const profiles = ref<ModelProfileResponse[]>([]);
const providers = ref<ProviderResponse[]>([]);

const categoryOptions: MenuOption[] = CATEGORIES.map(c => ({
  key: c.key,
  label: c.label,
}));

const selectedCategoryLabel = computed(() =>
  CATEGORIES.find(c => c.key === selectedCategory.value)?.label ?? "全部"
);

const filteredProfiles = computed(() => {
  if (selectedCategory.value === "all") return profiles.value;
  return profiles.value.filter(p =>
    p.purpose === selectedCategory.value ||
    (p.capability_tags && p.capability_tags.includes(selectedCategory.value))
  );
});



const modelColumns: DataTableColumns<ModelProfileResponse> = [
  { title: "名称", key: "name" },
  { title: "用途 (purpose)", key: "purpose", width: 160 },
  {
    title: "能力标签",
    key: "capability_tags",
    render: (row) =>
      h(NSpace, { size: 4 }, {
        default: () => (row.capability_tags || []).map((tag: string) =>
          h(NTag, { size: "small", type: "info" }, { default: () => tag })
        ),
      }),
  },
  { title: "Provider", key: "provider_id", width: 140 },
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
    profiles.value = m;
  } catch (e) {
    console.error("load failed", e);
  }
}

onMounted(() => {
  void onRefresh();
});
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
