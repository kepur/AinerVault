<template>
  <div class="page-grid">
    <NCard title="SKILL 25 · Language Settings（中英+小语种）">
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 900:1">
          <NFormItem label="Tenant ID">
            <NInput v-model:value="tenantId" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 900:1">
          <NFormItem label="Project ID">
            <NInput v-model:value="projectId" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 900:1">
          <NFormItem label="默认输入语言">
            <NInput v-model:value="defaultSourceLanguage" placeholder="zh-CN" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 900:1">
          <NFormItem label="默认输出语言列表（逗号）">
            <NInput v-model:value="defaultTargetLanguagesCsv" placeholder="en-US,ja-JP,es-ES" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NFormItem label="启用语言定义 JSON（含 RTL）">
        <NInput v-model:value="enabledLanguagesJson" type="textarea" :autosize="{ minRows: 8, maxRows: 14 }" />
      </NFormItem>
      <NFormItem label="翻译备注">
        <NInput v-model:value="translationNotes" type="textarea" :autosize="{ minRows: 2, maxRows: 4 }" />
      </NFormItem>
      <NFormItem label="术语表 JSON">
        <NInput v-model:value="glossaryJson" type="textarea" :autosize="{ minRows: 2, maxRows: 6 }" />
      </NFormItem>
      <NSpace>
        <NButton type="primary" @click="onSave">保存</NButton>
        <NButton @click="onLoad">加载</NButton>
      </NSpace>
      <pre class="json-panel">{{ responseText }}</pre>
    </NCard>

    <NAlert v-if="message" type="success" :show-icon="true">{{ message }}</NAlert>
    <NAlert v-if="errorMessage" type="error" :show-icon="true">{{ errorMessage }}</NAlert>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from "vue";
import {
  NAlert,
  NButton,
  NCard,
  NFormItem,
  NGrid,
  NGridItem,
  NInput,
  NSpace,
} from "naive-ui";

import {
  type LanguageDefinition,
  getLanguageSettings,
  upsertLanguageSettings,
} from "@/api/product";

const tenantId = ref("default");
const projectId = ref("default");

const defaultSourceLanguage = ref("zh-CN");
const defaultTargetLanguagesCsv = ref("en-US,ja-JP");
const enabledLanguagesJson = ref(
  JSON.stringify(
    [
      { language_code: "zh-CN", label: "简体中文", locales: ["zh-CN"], direction: "ltr", enabled: true },
      { language_code: "en-US", label: "English", locales: ["en-US", "en-GB"], direction: "ltr", enabled: true },
      { language_code: "ja-JP", label: "日本語", locales: ["ja-JP"], direction: "ltr", enabled: true },
      { language_code: "es-ES", label: "Español", locales: ["es-ES"], direction: "ltr", enabled: true },
      { language_code: "ar-SA", label: "العربية", locales: ["ar-SA"], direction: "rtl", enabled: true },
    ],
    null,
    2
  )
);
const translationNotes = ref("支持中英和小语种翻译输出");
const glossaryJson = ref('{"wuxia":{"en-US":"martial heroes"}}');
const responseText = ref("{}");

const message = ref("");
const errorMessage = ref("");

function stringifyError(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function clearNotice(): void {
  message.value = "";
  errorMessage.value = "";
}

function parseLanguages(text: string): LanguageDefinition[] {
  const value = JSON.parse(text) as unknown;
  if (!Array.isArray(value)) {
    throw new Error("enabled_languages must be array");
  }
  return value as LanguageDefinition[];
}

function parseObject(text: string): Record<string, unknown> {
  const value = JSON.parse(text) as unknown;
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("json must be object");
  }
  return value as Record<string, unknown>;
}

function parseTargets(csv: string): string[] {
  return csv
    .split(",")
    .map((item) => item.trim())
    .filter((item) => item.length > 0);
}

async function onSave(): Promise<void> {
  clearNotice();
  try {
    const response = await upsertLanguageSettings({
      tenant_id: tenantId.value,
      project_id: projectId.value,
      default_source_language: defaultSourceLanguage.value,
      default_target_languages: parseTargets(defaultTargetLanguagesCsv.value),
      enabled_languages: parseLanguages(enabledLanguagesJson.value),
      translation_notes: translationNotes.value,
      glossary: parseObject(glossaryJson.value),
      schema_version: "1.0",
    });
    responseText.value = JSON.stringify(response, null, 2);
    message.value = "language settings saved";
  } catch (error) {
    errorMessage.value = `save failed: ${stringifyError(error)}`;
  }
}

async function onLoad(): Promise<void> {
  clearNotice();
  try {
    const response = await getLanguageSettings(tenantId.value, projectId.value);
    defaultSourceLanguage.value = response.default_source_language;
    defaultTargetLanguagesCsv.value = response.default_target_languages.join(",");
    enabledLanguagesJson.value = JSON.stringify(response.enabled_languages, null, 2);
    translationNotes.value = response.translation_notes || "";
    glossaryJson.value = JSON.stringify(response.glossary || {}, null, 2);
    responseText.value = JSON.stringify(response, null, 2);
    message.value = "language settings loaded";
  } catch (error) {
    errorMessage.value = `load failed: ${stringifyError(error)}`;
  }
}

onMounted(() => {
  void onLoad();
});
</script>
