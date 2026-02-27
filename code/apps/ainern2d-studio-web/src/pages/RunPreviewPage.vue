<template>
  <div class="page-grid">
    <NCard title="Run Preview">
      <NText depth="3">Project: {{ props.projectId }} | Run: {{ props.runId }}</NText>
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Prompt (optional)">
            <NInput v-model:value="promptText" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Negative Prompt (optional)">
            <NInput v-model:value="negativePromptText" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NButton type="primary" @click="reloadAll">Reload</NButton>
      <NAlert v-if="errorMessage" type="error" :show-icon="true">{{ errorMessage }}</NAlert>
    </NCard>

    <NCard title="Entities">
      <NDataTable :columns="entityColumns" :data="entities" :pagination="{ pageSize: 8 }" />
    </NCard>

    <NCard :title="`Variants ${selectedEntityId ? `(entity: ${selectedEntityId})` : ''}`">
      <NDataTable :columns="variantColumns" :data="variants" :pagination="{ pageSize: 8 }" />
    </NCard>
  </div>
</template>

<script setup lang="ts">
import { h, onMounted, ref, watch } from "vue";
import { useRouter } from "vue-router";
import {
  NAlert,
  NButton,
  NCard,
  NDataTable,
  NFormItem,
  NGrid,
  NGridItem,
  NInput,
  NTag,
  NText,
  type DataTableColumns,
} from "naive-ui";

import {
  type PreviewEntity,
  type PreviewVariant,
  generatePreviewVariants,
  listPreviewEntities,
  listPreviewVariants,
  reviewPreviewVariant,
} from "@/api/preview";

const props = defineProps<{
  projectId: string;
  runId: string;
}>();

const router = useRouter();

const entities = ref<PreviewEntity[]>([]);
const variants = ref<PreviewVariant[]>([]);
const selectedEntityId = ref<string>("");
const promptText = ref<string>("");
const negativePromptText = ref<string>("");
const errorMessage = ref<string>("");

const entityColumns: DataTableColumns<PreviewEntity> = [
  { title: "Entity", key: "label" },
  { title: "ID", key: "entity_id" },
  { title: "Type", key: "entity_type" },
  {
    title: "Continuity",
    key: "continuity_status",
    render: (row) => h(NTag, { type: statusTagType(row.continuity_status), bordered: false }, { default: () => row.continuity_status }),
  },
  {
    title: "Voice",
    key: "voice_id",
    render: (row) => row.voice_id || "-",
  },
  {
    title: "Actions",
    key: "actions",
    render: (row) =>
      h("div", { style: "display:flex;gap:6px;flex-wrap:wrap;" }, [
        h(
          NButton,
          { size: "tiny", onClick: () => void loadEntityVariants(row.entity_id) },
          { default: () => "Load Variants" }
        ),
        h(
          NButton,
          { size: "tiny", type: "info", onClick: () => void generateForEntity(row.entity_id) },
          { default: () => "Generate 4-Angle" }
        ),
        row.entity_type === "person"
          ? h(
              NButton,
              {
                size: "tiny",
                type: "warning",
                onClick: () => {
                  void router.push({
                    name: "voice-binding",
                    params: { projectId: props.projectId, entityId: row.entity_id },
                  });
                },
              },
              { default: () => "Voice Binding" }
            )
          : null,
      ]),
  },
];

const variantColumns: DataTableColumns<PreviewVariant> = [
  { title: "Variant", key: "variant_id" },
  { title: "Entity", key: "entity_label" },
  { title: "Angle", key: "view_angle" },
  { title: "Backend", key: "generation_backend" },
  {
    title: "Status",
    key: "status",
    render: (row) => h(NTag, { type: statusTagType(row.status), bordered: false }, { default: () => row.status }),
  },
  {
    title: "Actions",
    key: "actions",
    render: (row) =>
      h("div", { style: "display:flex;gap:6px;flex-wrap:wrap;" }, [
        h(
          NButton,
          { size: "tiny", type: "success", onClick: () => void reviewVariant(row.variant_id, "approve") },
          { default: () => "Approve" }
        ),
        h(
          NButton,
          { size: "tiny", type: "error", onClick: () => void reviewVariant(row.variant_id, "reject") },
          { default: () => "Reject" }
        ),
        h(
          NButton,
          { size: "tiny", type: "warning", onClick: () => void reviewVariant(row.variant_id, "regenerate") },
          { default: () => "Regenerate" }
        ),
      ]),
  },
];

function statusTagType(status: string): "success" | "warning" | "error" | "default" {
  if (status.includes("approve") || status === "locked" || status === "ready") {
    return "success";
  }
  if (status.includes("reject") || status.includes("fail")) {
    return "error";
  }
  return "warning";
}

async function reloadEntities(): Promise<void> {
  entities.value = await listPreviewEntities(props.runId);
}

async function loadEntityVariants(entityId: string): Promise<void> {
  selectedEntityId.value = entityId;
  variants.value = await listPreviewVariants(props.runId, entityId);
}

async function reloadAll(): Promise<void> {
  errorMessage.value = "";
  try {
    await reloadEntities();
    if (selectedEntityId.value) {
      await loadEntityVariants(selectedEntityId.value);
    }
  } catch (error) {
    errorMessage.value = `load failed: ${String(error)}`;
  }
}

async function generateForEntity(entityId: string): Promise<void> {
  errorMessage.value = "";
  try {
    await generatePreviewVariants(props.runId, entityId, {
      prompt_text: promptText.value || undefined,
      negative_prompt_text: negativePromptText.value || undefined,
      view_angles: ["front", "three_quarter", "side", "back"],
    });
    await reloadAll();
    await loadEntityVariants(entityId);
  } catch (error) {
    errorMessage.value = `generate failed: ${String(error)}`;
  }
}

async function reviewVariant(variantId: string, decision: "approve" | "reject" | "regenerate"): Promise<void> {
  errorMessage.value = "";
  try {
    await reviewPreviewVariant(variantId, decision);
    await reloadAll();
  } catch (error) {
    errorMessage.value = `review failed: ${String(error)}`;
  }
}

onMounted(() => {
  void reloadAll();
});

watch(
  () => props.runId,
  () => {
    selectedEntityId.value = "";
    variants.value = [];
    void reloadAll();
  }
);
</script>
