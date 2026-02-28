<template>
  <div class="dashboard-grid">
    <!-- 系统状态概览 -->
    <NCard :title="t('dashboard.title')" :segmented="{ content: true }">
      <NGrid :cols="4" :x-gap="16" :y-gap="16" responsive="screen" item-responsive>
        <NGridItem span="0:2 900:1">
          <NStatistic :label="t('dashboard.providers')" :value="stats.providers" />
        </NGridItem>
        <NGridItem span="0:2 900:1">
          <NStatistic :label="t('dashboard.models')" :value="stats.models" />
        </NGridItem>
        <NGridItem span="0:2 900:1">
          <NStatistic :label="t('dashboard.novels')" :value="stats.novels" />
        </NGridItem>
        <NGridItem span="0:2 900:1">
          <NStatistic :label="t('dashboard.runs')" :value="stats.runs" />
        </NGridItem>
      </NGrid>
    </NCard>

    <!-- 快捷入口 -->
    <NCard :title="t('dashboard.quickEntry')">
      <NSpace wrap>
        <NButton type="primary" @click="goTo('/studio/novels')">{{ t('dashboard.go.novels') }}</NButton>
        <NButton @click="goTo('/studio/providers')">{{ t('dashboard.go.providers') }}</NButton>
        <NButton @click="goTo('/studio/model-catalog')">{{ t('dashboard.go.modelCatalog') }}</NButton>
        <NButton @click="goTo('/studio/kb-assets')">{{ t('dashboard.go.kbAssets') }}</NButton>
        <NButton @click="goTo('/studio/runs')">{{ t('dashboard.go.runs') }}</NButton>
        <NButton @click="goTo('/studio/roles/config')">{{ t('dashboard.go.roles') }}</NButton>
      </NSpace>
    </NCard>

    <!-- 初始化工具 -->
    <NCard :title="t('dashboard.sysInit')">
      <NSpace>
        <NButton type="warning" @click="onBootstrapDefaults">{{ t('dashboard.initBasic') }}</NButton>
        <NButton type="error" :loading="isBootstrapping" @click="onBootstrapAll">{{ t('dashboard.initAll') }}</NButton>
      </NSpace>
      <pre v-if="bootstrapText !== '{}'" class="json-panel" style="margin-top:12px">{{ bootstrapText }}</pre>
    </NCard>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import {
  NButton,
  NCard,
  NGrid,
  NGridItem,
  NSpace,
  NStatistic,
} from "naive-ui";
import { bootstrapAll, bootstrapDefaults, listNovels, listProviders, listModelProfiles } from "@/api/product";
import { useI18n } from "@/composables/useI18n";

const { t } = useI18n();
const router = useRouter();
const bootstrapText = ref("{}");
const isBootstrapping = ref(false);
const stats = reactive({ providers: 0, models: 0, novels: 0, runs: 0 });

function goTo(path: string): void {
  void router.push(path);
}

async function loadStats(): Promise<void> {
  try {
    const [providerList, novelList, profileList] = await Promise.all([
      listProviders("default", "default"),
      listNovels("default", "default"),
      listModelProfiles({ tenant_id: "default", project_id: "default" }),
    ]);
    stats.providers = providerList.length;
    stats.novels = novelList.length;
    stats.models = profileList.length;
  } catch {
    // silently load what we can
  }
}

async function onBootstrapAll(): Promise<void> {
  isBootstrapping.value = true;
  try {
    const response = await bootstrapAll({ tenant_id: "default", project_id: "default" });
    bootstrapText.value = JSON.stringify(response, null, 2);
  } catch (error) {
    bootstrapText.value = JSON.stringify({ error: String(error) }, null, 2);
  } finally {
    isBootstrapping.value = false;
  }
}

async function onBootstrapDefaults(): Promise<void> {
  try {
    const response = await bootstrapDefaults({
      tenant_id: "default",
      project_id: "default",
      seed_mode: "llm_template",
      include_roles: true,
      include_skills: true,
      include_routes: true,
      include_language_settings: true,
      include_stage_routing: true,
    });
    bootstrapText.value = JSON.stringify(response, null, 2);
  } catch (error) {
    bootstrapText.value = JSON.stringify({ error: String(error) }, null, 2);
  }
}

onMounted(() => {
  void loadStats();
});
</script>

<style scoped>
.dashboard-grid {
  display: flex;
  flex-direction: column;
  gap: 16px;
}
</style>
