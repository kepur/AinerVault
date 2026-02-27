<template>
  <div class="page-grid">
    <NCard title="SKILL 29 + 30 · Assets / Timeline Patch">
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Tenant ID">
            <NInput v-model:value="tenantId" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Project ID">
            <NInput v-model:value="projectId" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Run ID">
            <NInput v-model:value="runId" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Shot ID">
            <NInput v-model:value="shotId" />
          </NFormItem>
        </NGridItem>
      </NGrid>
    </NCard>

    <NCard title="Project Assets">
      <NSpace>
        <NButton type="primary" @click="onListAssets">Load Assets</NButton>
      </NSpace>
      <NDataTable :columns="assetColumns" :data="assets" :pagination="{ pageSize: 8 }" />
    </NCard>

    <NCard title="Anchor Asset">
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Asset ID">
            <NInput v-model:value="assetId" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Entity ID (optional)">
            <NInput v-model:value="entityId" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NFormItem label="Anchor Name">
        <NInput v-model:value="anchorName" />
      </NFormItem>
      <NFormItem label="Anchor Notes">
        <NInput v-model:value="anchorNotes" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" />
      </NFormItem>
      <NSpace>
        <NButton type="primary" @click="onAnchorAsset">Mark Anchor</NButton>
        <NButton @click="onListAnchors">Load Anchors</NButton>
      </NSpace>
      <pre class="json-panel">{{ anchorsText }}</pre>
    </NCard>

    <NCard title="Timeline + PR式 Patch Diff">
      <NSpace>
        <NButton type="primary" @click="onLoadTimeline">Load Timeline</NButton>
      </NSpace>

      <NDivider />

      <NDataTable :columns="promptColumns" :data="promptTrackItems" :pagination="{ pageSize: 6 }" />

      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 900:1">
          <NFormItem label="Original Prompt">
            <NInput :value="originalPromptText" type="textarea" :autosize="{ minRows: 6, maxRows: 12 }" readonly />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 900:1">
          <NFormItem label="Edited Prompt（Patch候选）">
            <NInput v-model:value="modifiedPromptText" type="textarea" :autosize="{ minRows: 6, maxRows: 12 }" />
          </NFormItem>
        </NGridItem>
      </NGrid>

      <NFormItem label="Patch Text（将提交到 rerun-shot）">
        <NInput v-model:value="patchText" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" />
      </NFormItem>

      <NText depth="3">Diff Preview（PR Style）</NText>
      <div class="diff-panel">
        <div v-for="(line, idx) in diffLines" :key="idx" :class="['diff-line', `diff-${line.kind}`]">
          <span class="diff-prefix">{{ line.kind === 'add' ? '+' : line.kind === 'remove' ? '-' : ' ' }}</span>
          <span>{{ line.text }}</span>
        </div>
      </div>

      <NSpace>
        <NButton type="warning" @click="onPatchTimeline">Patch + Rerun Shot</NButton>
      </NSpace>
      <pre class="json-panel">{{ patchResultText }}</pre>
      <pre class="json-panel">{{ timelineText }}</pre>
    </NCard>

    <NAlert v-if="message" type="success" :show-icon="true">{{ message }}</NAlert>
    <NAlert v-if="errorMessage" type="error" :show-icon="true">{{ errorMessage }}</NAlert>
  </div>
</template>

<script setup lang="ts">
import { computed, h, ref } from "vue";
import {
  NAlert,
  NButton,
  NCard,
  NDataTable,
  NDivider,
  NFormItem,
  NGrid,
  NGridItem,
  NInput,
  NSpace,
  NText,
  type DataTableColumns,
} from "naive-ui";

import {
  type ProjectAssetItem,
  getRunTimeline,
  listProjectAnchors,
  listProjectAssets,
  markAssetAnchor,
  patchRunTimeline,
} from "@/api/product";

interface PromptTrackItem {
  plan_id?: string;
  shot_id: string;
  prompt_text: string;
  negative_prompt_text?: string | null;
}

interface DiffLine {
  kind: "context" | "add" | "remove";
  text: string;
}

const tenantId = ref("default");
const projectId = ref("default");
const runId = ref("");
const shotId = ref("");

const assets = ref<ProjectAssetItem[]>([]);
const assetId = ref("");
const entityId = ref("");
const anchorName = ref("hero-reference");
const anchorNotes = ref("keep continuity");

const patchText = ref("improve lighting and camera movement");

const promptTrackItems = ref<PromptTrackItem[]>([]);
const originalPromptText = ref("");
const modifiedPromptText = ref("");

const anchorsText = ref("[]");
const timelineText = ref("{}");
const patchResultText = ref("{}");

const message = ref("");
const errorMessage = ref("");

const assetColumns: DataTableColumns<ProjectAssetItem> = [
  { title: "ID", key: "id" },
  { title: "Type", key: "type" },
  { title: "Run", key: "run_id" },
  { title: "Shot", key: "shot_id" },
  {
    title: "URI",
    key: "uri",
    render: (row) => h("span", { style: "font-size: 12px;" }, row.uri),
  },
  {
    title: "Action",
    key: "action",
    render: (row) =>
      h(
        NButton,
        {
          size: "small",
          onClick: () => onSelectAsset(row.id),
        },
        { default: () => "Select" }
      ),
  },
];

const promptColumns: DataTableColumns<PromptTrackItem> = [
  { title: "Shot", key: "shot_id" },
  {
    title: "Prompt",
    key: "prompt_text",
    render: (row) => h("span", { style: "font-size: 12px;" }, row.prompt_text.slice(0, 80)),
  },
  {
    title: "Action",
    key: "action",
    render: (row) =>
      h(
        NButton,
        {
          size: "small",
          type: "info",
          onClick: () => openPatchEditor(row),
        },
        { default: () => "Edit Patch" }
      ),
  },
];

const diffLines = computed<DiffLine[]>(() => buildDiffLines(originalPromptText.value, modifiedPromptText.value));

function stringifyError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

function toPrettyJson(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function clearNotice(): void {
  message.value = "";
  errorMessage.value = "";
}

function buildDiffLines(beforeText: string, afterText: string): DiffLine[] {
  const before = beforeText.split("\n");
  const after = afterText.split("\n");
  const result: DiffLine[] = [];
  let i = 0;
  let j = 0;

  while (i < before.length || j < after.length) {
    const b = before[i];
    const a = after[j];

    if (b === a) {
      if (b !== undefined) {
        result.push({ kind: "context", text: b });
      }
      i += 1;
      j += 1;
      continue;
    }

    if (a !== undefined && before[i] === after[j + 1]) {
      result.push({ kind: "add", text: a });
      j += 1;
      continue;
    }

    if (b !== undefined && before[i + 1] === after[j]) {
      result.push({ kind: "remove", text: b });
      i += 1;
      continue;
    }

    if (b !== undefined) {
      result.push({ kind: "remove", text: b });
    }
    if (a !== undefined) {
      result.push({ kind: "add", text: a });
    }
    i += 1;
    j += 1;
  }

  return result;
}

function openPatchEditor(item: PromptTrackItem): void {
  shotId.value = item.shot_id;
  originalPromptText.value = item.prompt_text || "";
  modifiedPromptText.value = item.prompt_text || "";
  patchText.value = item.prompt_text || patchText.value;
}

async function onListAssets(): Promise<void> {
  clearNotice();
  try {
    assets.value = await listProjectAssets({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      run_id: runId.value || undefined,
    });
  } catch (error) {
    errorMessage.value = `list assets failed: ${stringifyError(error)}`;
  }
}

function onSelectAsset(id: string): void {
  assetId.value = id;
}

async function onAnchorAsset(): Promise<void> {
  clearNotice();
  if (!assetId.value) {
    errorMessage.value = "asset_id is required";
    return;
  }
  try {
    const result = await markAssetAnchor(assetId.value, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      entity_id: entityId.value || undefined,
      anchor_name: anchorName.value,
      notes: anchorNotes.value,
    });
    message.value = `anchor set: ${result.asset_id}`;
  } catch (error) {
    errorMessage.value = `anchor asset failed: ${stringifyError(error)}`;
  }
}

async function onListAnchors(): Promise<void> {
  clearNotice();
  try {
    const items = await listProjectAnchors(projectId.value, tenantId.value);
    anchorsText.value = toPrettyJson(items);
  } catch (error) {
    errorMessage.value = `list anchors failed: ${stringifyError(error)}`;
  }
}

async function onLoadTimeline(): Promise<void> {
  clearNotice();
  if (!runId.value) {
    errorMessage.value = "run_id is required";
    return;
  }
  try {
    const timeline = await getRunTimeline(runId.value);
    timelineText.value = toPrettyJson(timeline);

    const timelinePayload = timeline as unknown as { effect_tracks?: Array<Record<string, unknown>> };
    const effectTracks = Array.isArray(timelinePayload.effect_tracks) ? timelinePayload.effect_tracks : [];
    const promptTrack = effectTracks.find((track) => track.track === "prompt");
    const promptItems = Array.isArray(promptTrack?.items)
      ? (promptTrack?.items as Array<Record<string, unknown>>)
      : [];
    promptTrackItems.value = promptItems.map((item) => ({
      plan_id: String(item.plan_id || ""),
      shot_id: String(item.shot_id || ""),
      prompt_text: String(item.prompt_text || ""),
      negative_prompt_text: item.negative_prompt_text ? String(item.negative_prompt_text) : null,
    }));

    if (promptTrackItems.value.length > 0) {
      openPatchEditor(promptTrackItems.value[0]);
    }
  } catch (error) {
    errorMessage.value = `load timeline failed: ${stringifyError(error)}`;
  }
}

async function onPatchTimeline(): Promise<void> {
  clearNotice();
  if (!runId.value || !shotId.value) {
    errorMessage.value = "run_id and shot_id are required";
    return;
  }
  try {
    const patchPayload = modifiedPromptText.value.trim() || patchText.value;
    const result = await patchRunTimeline(runId.value, {
      tenant_id: tenantId.value,
      project_id: projectId.value,
      shot_id: shotId.value,
      patch_text: patchPayload,
      track: "prompt",
      patch_scope: "rerun-shot",
      requested_by: "studio-web",
    });
    patchText.value = patchPayload;
    patchResultText.value = toPrettyJson(result);
    message.value = `patch queued: ${result.job_id}`;
  } catch (error) {
    errorMessage.value = `patch timeline failed: ${stringifyError(error)}`;
  }
}
</script>
