<template>
  <div class="page-grid">
    <NCard title="SKILL 27 · World / Culture Pack 管理">
      <NGrid :cols="3" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Tenant ID">
            <NInput v-model:value="tenantId" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Project ID">
            <NInput v-model:value="projectId" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="过滤关键字">
            <NInput v-model:value="keyword" placeholder="pack id or display name" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NSpace>
        <NButton type="primary" @click="onList">刷新列表</NButton>
      </NSpace>
    </NCard>

    <NCard title="Create / Update Culture Pack">
      <NGrid :cols="3" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Culture Pack ID">
            <NInput v-model:value="culturePackId" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Display Name">
            <NInput v-model:value="displayName" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:3 900:1">
          <NFormItem label="Version">
            <NInput v-model:value="version" placeholder="v1" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NFormItem label="Description">
        <NInput v-model:value="description" />
      </NFormItem>
      <NFormItem label="Constraints JSON">
        <NInput v-model:value="constraintsJson" type="textarea" :autosize="{ minRows: 4, maxRows: 8 }" />
      </NFormItem>
      <NSpace>
        <NButton type="primary" @click="onCreate">新增/更新</NButton>
        <NButton type="info" :disabled="!culturePackId" @click="onExport">导出约束</NButton>
      </NSpace>
      <pre class="json-panel">{{ exportText }}</pre>
    </NCard>

    <!-- LLM 一键提取 -->
    <NCard title="🤖 LLM 一键提取文化包">
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Provider ID（LLM模型）">
            <NInput v-model:value="llmProviderId" placeholder="输入 Model Provider ID" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 640:1">
          <NFormItem label="目标文化包 ID（可选，留空则创建新包）">
            <NInput v-model:value="llmTargetPackId" placeholder="留空自动生成" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NFormItem label="世界观描述（输入越详细，提取越准确）">
        <NInput
          v-model:value="worldDescription"
          type="textarea"
          :autosize="{ minRows: 5, maxRows: 12 }"
          placeholder="描述这个世界的时代背景、视觉风格、文化特征、禁忌事项..."
        />
      </NFormItem>
      <NSpace>
        <NButton
          type="primary"
          :loading="isLlmExtracting"
          :disabled="!llmProviderId || !worldDescription || isLlmExtracting"
          @click="onLlmExtract"
        >
          {{ isLlmExtracting ? 'LLM 提取中...' : '🤖 LLM 一键提取' }}
        </NButton>
      </NSpace>
      <div v-if="llmExtractResult" style="margin-top: 12px;">
        <NTag type="success" :bordered="false">✓ 已提取：{{ llmExtractResult.culture_pack_id }} @ {{ llmExtractResult.version }}</NTag>
        <pre class="json-panel">{{ JSON.stringify(llmExtractResult.constraints, null, 2) }}</pre>
      </div>
    </NCard>

    <NCard title="Culture Pack 列表">
      <NDataTable :columns="columns" :data="packs" :pagination="{ pageSize: 8 }" />
    </NCard>

    <NAlert v-if="message" type="success" :show-icon="true">{{ message }}</NAlert>
    <NAlert v-if="errorMessage" type="error" :show-icon="true">{{ errorMessage }}</NAlert>
  </div>
</template>

<script setup lang="ts">
import { h, onMounted, ref } from "vue";
import {
  NAlert,
  NButton,
  NCard,
  NDataTable,
  NFormItem,
  NGrid,
  NGridItem,
  NInput,
  NSpace,
  type DataTableColumns,
} from "naive-ui";
import { useI18n } from "@/composables/useI18n";


import {
  type CulturePackLlmExtractResponse,
  type CulturePackResponse,
  createCulturePack,
  deleteCulturePack,
  exportCulturePack,
  extractCulturePackLlm,
  listCulturePacks,
} from "@/api/product";

const { t } = useI18n();

const tenantId = ref("default");
const projectId = ref("default");
const keyword = ref("");

const culturePackId = ref("cn_wuxia");
const displayName = ref("中式武侠");
const version = ref("v1");
const description = ref("默认文化包");
const constraintsJson = ref('{"visual_do":["ink"],"visual_dont":["neon"],"signage_rules":["hanzi"]}');

const packs = ref<CulturePackResponse[]>([]);
const exportText = ref("{}");
const message = ref("");
const errorMessage = ref("");

// LLM 提取状态
const llmProviderId = ref("");
const llmTargetPackId = ref("");
const worldDescription = ref("");
const isLlmExtracting = ref(false);
const llmExtractResult = ref<CulturePackLlmExtractResponse | null>(null);

const columns: DataTableColumns<CulturePackResponse> = [
  { title: "Pack ID", key: "culture_pack_id" },
  { title: "Version", key: "version" },
  { title: "Display Name", key: "display_name" },
  { title: "Status", key: "status" },
  {
    title: "Action",
    key: "action",
    render: (row) =>
      h(NSpace, { size: 6 }, {
        default: () => [
          h(NButton, { size: "tiny", onClick: () => {
            culturePackId.value = row.culture_pack_id;
            displayName.value = row.display_name;
            version.value = row.version;
            constraintsJson.value = JSON.stringify(row.constraints || {}, null, 2);
          } }, { default: () => "Use" }),
          h(NButton, { size: "tiny", type: "error", onClick: () => void onDelete(row.culture_pack_id) }, { default: () => "Delete" }),
        ],
      }),
  },
];

function stringifyError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function clearNotice(): void {
  message.value = "";
  errorMessage.value = "";
}

function parseConstraints(text: string): Record<string, unknown> {
  const parsed = JSON.parse(text) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("constraints must be object");
  }
  return parsed as Record<string, unknown>;
}

async function onList(): Promise<void> {
  clearNotice();
  try {
    packs.value = await listCulturePacks({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      keyword: keyword.value || undefined,
    });
  } catch (error) {
    errorMessage.value = `list culture packs failed: ${stringifyError(error)}`;
  }
}

async function onCreate(): Promise<void> {
  clearNotice();
  try {
    const created = await createCulturePack({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      culture_pack_id: culturePackId.value,
      display_name: displayName.value,
      description: description.value,
      constraints: parseConstraints(constraintsJson.value),
    });
    culturePackId.value = created.culture_pack_id;
    version.value = created.version;
    await onList();
    message.value = `culture pack upserted: ${created.culture_pack_id}@${created.version}`;
  } catch (error) {
    errorMessage.value = `create culture pack failed: ${stringifyError(error)}`;
  }
}

async function onExport(): Promise<void> {
  clearNotice();
  try {
    const exported = await exportCulturePack({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      culture_pack_id: culturePackId.value,
    });
    exportText.value = JSON.stringify(exported, null, 2);
  } catch (error) {
    errorMessage.value = `export failed: ${stringifyError(error)}`;
  }
}

async function onDelete(packId: string): Promise<void> {
  clearNotice();
  try {
    await deleteCulturePack(packId, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
    });
    await onList();
    message.value = `culture pack deleted: ${packId}`;
  } catch (error) {
    errorMessage.value = `delete failed: ${stringifyError(error)}`;
  }
}

async function onLlmExtract(): Promise<void> {
  clearNotice();
  if (!llmProviderId.value || !worldDescription.value.trim()) {
    errorMessage.value = "请填写 Provider ID 和世界观描述";
    return;
  }
  isLlmExtracting.value = true;
  try {
    llmExtractResult.value = await extractCulturePackLlm({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      model_provider_id: llmProviderId.value,
      world_description: worldDescription.value,
      culture_pack_id: llmTargetPackId.value || undefined,
    });
    // Populate the create form with extracted data
    if (llmExtractResult.value) {
      culturePackId.value = llmExtractResult.value.culture_pack_id;
      displayName.value = llmExtractResult.value.display_name;
      constraintsJson.value = JSON.stringify(llmExtractResult.value.constraints, null, 2);
    }
    await onList();
    message.value = `LLM 提取完成：${llmExtractResult.value?.culture_pack_id}`;
  } catch (error) {
    errorMessage.value = `LLM 提取失败: ${stringifyError(error)}`;
  } finally {
    isLlmExtracting.value = false;
  }
}

onMounted(() => {
  void onList();
});
</script>
