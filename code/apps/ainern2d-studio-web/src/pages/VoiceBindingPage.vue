<template>
  <section class="grid">
    <article class="card">
      <h2>Voice Binding</h2>
      <p class="muted">Project: {{ projectId }} | Entity: {{ entityId }}</p>
      <div class="grid cols-2">
        <div>
          <label>Language</label>
          <input v-model="form.language_code" />
        </div>
        <div>
          <label>Voice ID</label>
          <input v-model="form.voice_id" placeholder="narrator / male_zh / custom_voice_id" />
        </div>
        <div>
          <label>TTS Model</label>
          <input v-model="form.tts_model" />
        </div>
        <div>
          <label>Provider</label>
          <input v-model="form.provider" />
        </div>
      </div>
      <div>
        <label>Notes</label>
        <textarea rows="3" v-model="form.notes"></textarea>
      </div>
      <div class="button-row">
        <label>
          <input type="checkbox" v-model="form.locked" />
          lock voice
        </label>
        <button @click="saveBinding">Save</button>
      </div>
      <p v-if="message" class="badge ok">{{ message }}</p>
      <p v-if="errorMessage" class="badge bad">{{ errorMessage }}</p>
    </article>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";

import { getVoiceBinding, upsertVoiceBinding } from "@/api/preview";

const props = defineProps<{
  projectId: string;
  entityId: string;
}>();

const projectId = props.projectId;
const entityId = props.entityId;

const form = reactive({
  language_code: "zh-CN",
  voice_id: "narrator",
  tts_model: "tts-1",
  provider: "openai",
  locked: true,
  notes: "",
});

const message = ref("");
const errorMessage = ref("");

async function loadBinding(): Promise<void> {
  message.value = "";
  errorMessage.value = "";
  try {
    const binding = await getVoiceBinding(projectId, entityId, form.language_code);
    form.voice_id = binding.voice_id;
    form.tts_model = binding.tts_model;
    form.provider = binding.provider;
    form.locked = binding.locked;
    form.notes = binding.notes ?? "";
  } catch {
    // Keep defaults when no binding exists.
  }
}

async function saveBinding(): Promise<void> {
  message.value = "";
  errorMessage.value = "";
  try {
    await upsertVoiceBinding(projectId, entityId, {
      language_code: form.language_code,
      voice_id: form.voice_id,
      tts_model: form.tts_model,
      provider: form.provider,
      locked: form.locked,
      notes: form.notes || undefined,
    });
    message.value = "voice binding saved";
  } catch (error) {
    errorMessage.value = `save failed: ${String(error)}`;
  }
}

onMounted(() => {
  void loadBinding();
});
</script>
