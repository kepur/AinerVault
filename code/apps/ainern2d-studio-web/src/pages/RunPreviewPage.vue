<template>
  <section class="grid">
    <article class="card">
      <h2>Run Preview</h2>
      <p class="muted">Project: {{ props.projectId }} | Run: {{ props.runId }}</p>
      <div class="grid cols-2">
        <div>
          <label>Prompt (optional)</label>
          <textarea v-model="promptText" rows="2" />
        </div>
        <div>
          <label>Negative Prompt (optional)</label>
          <textarea v-model="negativePromptText" rows="2" />
        </div>
      </div>
      <div class="button-row">
        <button @click="reloadAll">Reload</button>
      </div>
      <p v-if="errorMessage" class="badge bad">{{ errorMessage }}</p>
    </article>

    <article class="card">
      <h3>Entities</h3>
      <p class="muted">Continuity candidates from SKILL 21 + preview variants.</p>
      <div class="list">
        <div class="card" v-for="entity in entities" :key="entity.entity_id">
          <div class="grid cols-2">
            <div>
              <strong>{{ entity.label }}</strong>
              <p class="muted">ID: {{ entity.entity_id }} | Type: {{ entity.entity_type }}</p>
              <p class="muted">
                Continuity: <span :class="statusClass(entity.continuity_status)" class="badge">{{ entity.continuity_status }}</span>
                <span v-if="entity.voice_id" class="badge ok">voice: {{ entity.voice_id }}</span>
              </p>
            </div>
            <div class="button-row">
              <button @click="loadEntityVariants(entity.entity_id)">Load Variants</button>
              <button @click="generateForEntity(entity.entity_id)">Generate 4-Angle</button>
              <RouterLink
                v-if="entity.entity_type === 'person'"
                :to="{
                  name: 'voice-binding',
                  params: { projectId: props.projectId, entityId: entity.entity_id }
                }"
              >
                Voice Binding
              </RouterLink>
            </div>
          </div>
        </div>
      </div>
      <p v-if="!entities.length" class="muted">No entities found for this run.</p>
    </article>

    <article class="card">
      <h3>Variants {{ selectedEntityId ? `(entity: ${selectedEntityId})` : "" }}</h3>
      <div class="list">
        <div class="card" v-for="variant in variants" :key="variant.variant_id">
          <div class="grid cols-2">
            <div>
              <strong>{{ variant.entity_label }}</strong>
              <p class="muted">
                Variant: {{ variant.variant_id }} | Angle: {{ variant.view_angle }} | Backend: {{ variant.generation_backend }}
              </p>
              <p class="muted">
                Status:
                <span class="badge" :class="statusClass(variant.status)">{{ variant.status }}</span>
                <span v-if="variant.artifact_uri" class="badge ok">artifact ready</span>
              </p>
            </div>
            <div class="button-row">
              <button @click="reviewVariant(variant.variant_id, 'approve')">Approve</button>
              <button @click="reviewVariant(variant.variant_id, 'reject')">Reject</button>
              <button @click="reviewVariant(variant.variant_id, 'regenerate')">Regenerate</button>
            </div>
          </div>
        </div>
      </div>
      <p v-if="!variants.length" class="muted">No variants loaded.</p>
    </article>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref, watch } from "vue";

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

const entities = ref<PreviewEntity[]>([]);
const variants = ref<PreviewVariant[]>([]);
const selectedEntityId = ref<string>("");
const promptText = ref<string>("");
const negativePromptText = ref<string>("");
const errorMessage = ref<string>("");

function statusClass(status: string): string {
  if (status.includes("approve") || status === "locked" || status === "ready") {
    return "ok";
  }
  if (status.includes("reject") || status.includes("fail")) {
    return "bad";
  }
  return "warn";
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
