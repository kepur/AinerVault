<template>
  <div class="page-grid two">
    <NCard title="Studio 产品层联调入口" :segmented="{ content: true }">
      <NSpace vertical>
        <NText depth="3">覆盖 SKILL 23~30：鉴权、内容管理、任务运行、配置中心、素材与时间线。</NText>
        <NSpace wrap>
          <NButton type="primary" @click="goTo('studio-auth-users')">23 账号与权限</NButton>
          <NButton @click="goTo('studio-role-config')">角色配置中心</NButton>
          <NButton @click="goTo('studio-roles')">Role Workbench</NButton>
          <NButton @click="goTo('studio-novels')">24 小说管理</NButton>
          <NButton @click="goTo('studio-chapter-workspace')">24 章节工作区</NButton>
          <NButton @click="goTo('studio-runs')">28 任务运行中心</NButton>
          <NButton @click="goTo('studio-providers')">25 Provider接入</NButton>
          <NButton @click="goTo('studio-model-routing')">25 模型档案与路由</NButton>
          <NButton @click="goTo('studio-languages')">25 多语言</NButton>
          <NButton @click="goTo('studio-rag')">26 RAG与导演</NButton>
          <NButton @click="goTo('studio-culture')">27 文化包</NButton>
          <NButton @click="goTo('studio-asset-library')">29 素材库</NButton>
          <NButton @click="goTo('studio-asset-bindings')">29 素材绑定一致性</NButton>
          <NButton @click="goTo('studio-timeline')">30 PR时间线</NButton>
          <NButton type="warning" @click="onBootstrapDefaults">一键初始化基础数据</NButton>
        </NSpace>
        <pre class="json-panel">{{ bootstrapText }}</pre>
      </NSpace>
    </NCard>

    <NCard title="打开 Run 预览工具">
      <NSpace vertical>
        <NForm label-placement="top">
          <NFormItem label="Project ID">
            <NInput v-model:value="projectId" placeholder="project_xxx" />
          </NFormItem>
          <NFormItem label="Run ID">
            <NInput v-model:value="runId" placeholder="run_xxx" />
          </NFormItem>
        </NForm>
        <NButton type="info" @click="openPreview" :disabled="!projectId || !runId">打开预览</NButton>
      </NSpace>
    </NCard>

    <NCard title="MVP 闭环范围" class="mvp-card">
      <NList bordered>
        <NListItem>Entity continuity profile 与 approved variant lock。</NListItem>
        <NListItem>多角度 preview 生成与审核回路。</NListItem>
        <NListItem>Task/Run 冻结快照与可回溯配置。</NListItem>
        <NListItem>Timeline patch 到 rerun-shot 的重生成入口。</NListItem>
      </NList>
    </NCard>
  </div>
</template>

<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";
import {
  NButton,
  NCard,
  NForm,
  NFormItem,
  NInput,
  NList,
  NListItem,
  NSpace,
  NText,
} from "naive-ui";
import { bootstrapDefaults } from "@/api/product";

const router = useRouter();
const projectId = ref("");
const runId = ref("");
const bootstrapText = ref("{}");

function goTo(name: string): void {
  void router.push({ name });
}

function openPreview(): void {
  if (!projectId.value || !runId.value) {
    return;
  }
  void router.push({
    name: "run-preview",
    params: {
      projectId: projectId.value,
      runId: runId.value,
    },
  });
}

async function onBootstrapDefaults(): Promise<void> {
  try {
    const response = await bootstrapDefaults({
      tenant_id: "default",
      project_id: "default",
      seed_mode: "llm_template",
      include_roles: true,
      include_skills: true,
      include_routes: true,
      include_language_settings: true,
      include_stage_routing: true,
    });
    bootstrapText.value = JSON.stringify(response, null, 2);
  } catch (error) {
    bootstrapText.value = JSON.stringify({ error: String(error) }, null, 2);
  }
}
</script>
