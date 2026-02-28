<template>
  <div class="page-grid">
    <NCard title="Voice Binding">
      <NText depth="3">Project: {{ projectId }} | Entity: {{ entityId }}</NText>
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Language">
            <NInput v-model:value="form.language_code" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Voice ID">
            <NInput v-model:value="form.voice_id" placeholder="narrator / male_zh / custom_voice_id" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 640:1">
          <NFormItem label="TTS Model">
            <NInput v-model:value="form.tts_model" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Provider">
            <NInput v-model:value="form.provider" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NFormItem label="Notes">
        <NInput v-model:value="form.notes" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" />
      </NFormItem>
      <NSpace justify="space-between" align="center">
        <NSwitch v-model:value="form.locked">
          <template #checked>Locked</template>
          <template #unchecked>Unlocked</template>
        </NSwitch>
        <NButton type="primary" @click="saveBinding">{{ t('common.save') }}</NButton>
      </NSpace>
    </NCard>

    <NAlert v-if="message" type="success" :show-icon="true">{{ message }}</NAlert>
    <NAlert v-if="errorMessage" type="error" :show-icon="true">{{ errorMessage }}</NAlert>
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from "vue";
import {
  NAlert,
  NButton,
  NCard,
  NFormItem,
  NGrid,
  NGridItem,
  NInput,
  NSpace,
  NSwitch,
  NText,
} from "naive-ui";
import { useI18n } from "@/composables/useI18n";


import { getVoiceBinding, upsertVoiceBinding } from "@/api/preview";

const props = defineProps<{
  projectId: string;
  entityId: string;
}>();

const projectId = props.projectId;
const entityId = props.entityId;

const { t } = useI18n();

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
