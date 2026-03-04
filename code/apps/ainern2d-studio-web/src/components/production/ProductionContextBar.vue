<template>
  <NCard title="Production Context">
    <NGrid :cols="3" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
      <NGridItem span="0:3 1200:1">
        <NFormItem label="Novel">
          <NSelect
            :value="novelId"
            :options="novelOptions"
            filterable
            clearable
            :disabled="loading"
            @update:value="(v) => emit('update:novelId', (v || '') as string)"
          />
        </NFormItem>
      </NGridItem>
      <NGridItem span="0:3 1200:1">
        <NFormItem label="Chapter">
          <NSelect
            :value="chapterId"
            :options="chapterOptions"
            filterable
            clearable
            :disabled="loading || !novelId"
            @update:value="(v) => emit('update:chapterId', (v || '') as string)"
          />
        </NFormItem>
      </NGridItem>
      <NGridItem span="0:3 1200:1">
        <NFormItem label="Persona">
          <NSelect
            :value="personaPackId"
            :options="personaOptions"
            filterable
            clearable
            :disabled="loading"
            @update:value="(v) => emit('update:personaPackId', (v || '') as string)"
          />
        </NFormItem>
      </NGridItem>

      <NGridItem span="0:3 1200:1">
        <NFormItem label="Script Version">
          <NSelect
            :value="scriptVersion"
            :options="scriptVersionOptions"
            :disabled="loading || !chapterId"
            @update:value="(v) => emit('update:scriptVersion', (v || '') as string)"
          />
        </NFormItem>
      </NGridItem>
      <NGridItem span="0:3 1200:1">
        <NFormItem label="Plan Version">
          <NSelect
            :value="planVersion"
            :options="planVersionOptions"
            :disabled="loading || !chapterId"
            @update:value="(v) => emit('update:planVersion', (v || '') as string)"
          />
        </NFormItem>
      </NGridItem>
      <NGridItem span="0:3 1200:1">
        <NFormItem label="Quality">
          <NSelect
            :value="quality"
            :options="qualityOptions"
            :disabled="loading"
            @update:value="(v) => emit('update:quality', (v || 'standard') as string)"
          />
        </NFormItem>
      </NGridItem>

      <NGridItem span="0:3">
        <NFormItem label="Execution Tracks">
          <NSelect
            :value="selectedTracks"
            :options="trackOptions"
            multiple
            :disabled="loading"
            @update:value="(v) => emit('update:selectedTracks', ((v || []) as string[]))"
          />
        </NFormItem>
        <NSpace size="small" wrap>
          <NTag
            v-for="track in trackOptions"
            :key="track.value"
            size="small"
            :type="selectedTracks.includes(track.value) ? 'success' : 'default'"
            :bordered="false"
          >
            {{ track.label }}
          </NTag>
        </NSpace>
        <NSpace size="small">
          <NButton size="tiny" @click="emit('use-track-preset', 'audio')">Audio Only</NButton>
          <NButton size="tiny" @click="emit('use-track-preset', 'visual')">Visual Only</NButton>
          <NButton size="tiny" @click="emit('use-track-preset', 'all')">All Tracks</NButton>
        </NSpace>
      </NGridItem>
    </NGrid>

    <NSpace>
      <NButton type="primary" :loading="running" :disabled="!chapterId" @click="emit('create-run')">Create Run</NButton>
      <NButton :loading="running" :disabled="!runId" @click="emit('init-tracks', false)">Init Tracks</NButton>
      <NButton :loading="running" :disabled="!runId" @click="emit('init-tracks', true)">Rebuild Tracks</NButton>
      <NButton type="info" :loading="running" :disabled="!runId" @click="emit('run-selected')">Run Selected Tracks</NButton>
      <NButton :disabled="!runId" @click="emit('refresh')">Refresh</NButton>
    </NSpace>
  </NCard>
</template>

<script setup lang="ts">
import { NButton, NCard, NFormItem, NGrid, NGridItem, NSelect, NSpace, NTag } from "naive-ui";

defineProps<{
  loading: boolean;
  running: boolean;
  runId: string;
  novelId: string;
  chapterId: string;
  scriptVersion: string;
  planVersion: string;
  personaPackId: string;
  quality: string;
  selectedTracks: string[];
  novelOptions: Array<{ label: string; value: string }>;
  chapterOptions: Array<{ label: string; value: string }>;
  scriptVersionOptions: Array<{ label: string; value: string }>;
  planVersionOptions: Array<{ label: string; value: string }>;
  personaOptions: Array<{ label: string; value: string }>;
  qualityOptions: Array<{ label: string; value: string }>;
  trackOptions: Array<{ label: string; value: string }>;
}>();

const emit = defineEmits<{
  (event: "update:novelId", value: string): void;
  (event: "update:chapterId", value: string): void;
  (event: "update:scriptVersion", value: string): void;
  (event: "update:planVersion", value: string): void;
  (event: "update:personaPackId", value: string): void;
  (event: "update:quality", value: string): void;
  (event: "update:selectedTracks", value: string[]): void;
  (event: "use-track-preset", value: "audio" | "visual" | "all"): void;
  (event: "create-run"): void;
  (event: "init-tracks", recreate: boolean): void;
  (event: "run-selected"): void;
  (event: "refresh"): void;
}>();
</script>
