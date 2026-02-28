<template>
  <div class="notifications-page">
    <NCard :title="t('notifications.title')">
      <NText depth="3" style="display:block;margin-bottom:16px">
        配置系统通知渠道。Run 状态变化、任务失败等事件会通过已启用的渠道发送通知。
      </NText>
    </NCard>

    <NTabs type="card" animated>
      <!-- Telegram -->
      <NTabPane name="telegram" tab="🤖 Telegram">
        <NCard>
          <NForm label-placement="top">
            <NFormItem label="Telegram Bot Token">
              <NInput v-model:value="tgConfig.bot_token" type="password" show-password-on="click" placeholder="123456:ABC-DEF..." />
            </NFormItem>
            <NFormItem label="默认 Chat ID">
              <NInput v-model:value="tgConfig.default_chat_id" placeholder="-1001234567890" />
            </NFormItem>
            <NFormItem label="事件订阅">
              <NCheckboxGroup v-model:value="tgConfig.events">
                <NSpace>
                  <NCheckbox value="run_started" label="Run 开始" />
                  <NCheckbox value="run_completed" label="Run 完成" />
                  <NCheckbox value="run_failed" label="Run 失败" />
                  <NCheckbox value="approval_needed" label="需要人工审批" />
                  <NCheckbox value="entity_conflict" label="实体冲突" />
                </NSpace>
              </NCheckboxGroup>
            </NFormItem>
          </NForm>
          <NButton type="primary" @click="onSaveTelegram" :loading="isSaving">保存 Telegram 配置</NButton>
        </NCard>
      </NTabPane>

      <!-- SMTP -->
      <NTabPane name="smtp" :tab="t('notifications.smtp')">
        <NCard>
          <NForm label-placement="top">
            <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
              <NGridItem span="0:2 900:1">
                <NFormItem label="SMTP Host"><NInput v-model:value="smtpConfig.host" placeholder="smtp.gmail.com" /></NFormItem>
              </NGridItem>
              <NGridItem span="0:2 900:1">
                <NFormItem label="Port"><NInputNumber v-model:value="smtpConfig.port" :min="1" :max="65535" /></NFormItem>
              </NGridItem>
              <NGridItem span="0:2 900:1">
                <NFormItem label="Username"><NInput v-model:value="smtpConfig.username" /></NFormItem>
              </NGridItem>
              <NGridItem span="0:2 900:1">
                <NFormItem label="Password"><NInput v-model:value="smtpConfig.password" type="password" show-password-on="click" /></NFormItem>
              </NGridItem>
              <NGridItem span="0:2">
                <NFormItem label="From Address"><NInput v-model:value="smtpConfig.from_address" placeholder="noreply@ainer.ai" /></NFormItem>
              </NGridItem>
            </NGrid>
            <NFormItem label="事件订阅">
              <NCheckboxGroup v-model:value="smtpConfig.events">
                <NSpace>
                  <NCheckbox value="run_completed" label="Run 完成" />
                  <NCheckbox value="run_failed" label="Run 失败" />
                  <NCheckbox value="approval_needed" label="需要人工审批" />
                </NSpace>
              </NCheckboxGroup>
            </NFormItem>
          </NForm>
          <NButton type="primary" @click="onSaveSmtp" :loading="isSaving">保存 SMTP 配置</NButton>
        </NCard>
      </NTabPane>

      <!-- Webhook -->
      <NTabPane name="webhook" tab="🔗 Webhook">
        <NCard>
          <NForm label-placement="top">
            <NFormItem label="Webhook URL">
              <NInput v-model:value="webhookConfig.url" placeholder="https://example.com/webhook" />
            </NFormItem>
            <NFormItem label="Secret（签名验证）">
              <NInput v-model:value="webhookConfig.secret" type="password" show-password-on="click" />
            </NFormItem>
            <NFormItem label="事件订阅">
              <NCheckboxGroup v-model:value="webhookConfig.events">
                <NSpace>
                  <NCheckbox value="run_started" label="Run 开始" />
                  <NCheckbox value="run_completed" label="Run 完成" />
                  <NCheckbox value="run_failed" label="Run 失败" />
                  <NCheckbox value="approval_needed" label="需要人工审批" />
                </NSpace>
              </NCheckboxGroup>
            </NFormItem>
          </NForm>
          <NButton type="primary" @click="onSaveWebhook" :loading="isSaving">保存 Webhook 配置</NButton>
        </NCard>
      </NTabPane>
    </NTabs>

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
  NCheckbox,
  NCheckboxGroup,
  NForm,
  NFormItem,
  NGrid,
  NGridItem,
  NInput,
  NInputNumber,
  NSpace,
  NTabPane,
  NTabs,
  NText,
} from "naive-ui";
import { useI18n } from "@/composables/useI18n";

import { http } from "@/api/http";

const { t } = useI18n();

const isSaving = ref(false);
const message = ref("");
const errorMessage = ref("");

const tgConfig = reactive({
  bot_token: "",
  default_chat_id: "",
  events: [] as string[],
});

const smtpConfig = reactive({
  host: "",
  port: 587,
  username: "",
  password: "",
  from_address: "",
  events: [] as string[],
});

const webhookConfig = reactive({
  url: "",
  secret: "",
  events: [] as string[],
});

function clearNotice(): void {
  message.value = "";
  errorMessage.value = "";
}

async function loadSettings(): Promise<void> {
  try {
    const { data } = await (http as any).get("/api/v1/config/notification-settings", {
      params: { tenant_id: "default", project_id: "default" },
    });
    if (data.telegram) Object.assign(tgConfig, data.telegram);
    if (data.smtp) Object.assign(smtpConfig, data.smtp);
    if (data.webhook) Object.assign(webhookConfig, data.webhook);
  } catch {
    // settings may not exist yet
  }
}

async function saveAll(channel: string, config: Record<string, unknown>): Promise<void> {
  clearNotice();
  isSaving.value = true;
  try {
    await (http as any).put("/api/v1/config/notification-settings", {
      tenant_id: "default",
      project_id: "default",
      channel,
      config,
    });
    message.value = `${channel} 配置已保存`;
  } catch (error) {
    errorMessage.value = `保存失败: ${error instanceof Error ? error.message : String(error)}`;
  } finally {
    isSaving.value = false;
  }
}

function onSaveTelegram(): void { void saveAll("telegram", { ...tgConfig }); }
function onSaveSmtp(): void { void saveAll("smtp", { ...smtpConfig }); }
function onSaveWebhook(): void { void saveAll("webhook", { ...webhookConfig }); }

onMounted(() => { void loadSettings(); });
</script>

<style scoped>
.notifications-page {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
</style>
