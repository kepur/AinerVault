<template>
  <div class="page-grid">
    <NTabs v-model:value="activeTab" type="card" animated>
      <NTabPane name="catalog" :tab="t('models.modelList')">
        <StudioModelCatalogPage />
      </NTabPane>
      <NTabPane name="providers" :tab="t('models.providerApi')">
        <StudioProviderRouterPage />
      </NTabPane>
    </NTabs>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { NTabs, NTabPane } from "naive-ui";
import { useI18n } from "@/composables/useI18n";

import StudioModelCatalogPage from "./StudioModelCatalogPage.vue";
import StudioProviderRouterPage from "./StudioProviderRouterPage.vue";

const { t } = useI18n();

const activeTab = ref("catalog");
</script>

<style scoped>
.page-grid {
  padding: 8px 16px;
  position: relative;
  min-height: calc(100vh - 120px);
}
</style>
