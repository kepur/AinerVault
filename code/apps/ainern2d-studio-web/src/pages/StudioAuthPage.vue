<template>
  <div class="page-grid">
    <NCard title="SKILL 23 · Auth / ACL / Audit">
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
      </NGrid>
      <NTag type="success" :bordered="false">当前登录 Token：{{ authStore.token || "(none)" }}</NTag>
    </NCard>

    <NCard title="用户注册 / 登录">
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Username">
            <NInput v-model:value="username" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Email（登录账号）">
            <NInput v-model:value="email" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Password">
            <NInput v-model:value="password" type="password" show-password-on="click" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Current User ID">
            <NInput v-model:value="userId" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NSpace>
        <NButton type="primary" @click="onRegister">注册</NButton>
        <NButton type="info" @click="onLogin">登录</NButton>
        <NButton @click="onLogout">退出</NButton>
      </NSpace>
    </NCard>

    <NCard title="Project ACL">
      <NGrid :cols="2" :x-gap="12" :y-gap="8" responsive="screen" item-responsive>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Target User ID">
            <NInput v-model:value="aclUserId" />
          </NFormItem>
        </NGridItem>
        <NGridItem span="0:2 640:1">
          <NFormItem label="Role">
            <NSelect v-model:value="aclRole" :options="roleOptions" />
          </NFormItem>
        </NGridItem>
      </NGrid>
      <NSpace>
        <NButton type="primary" @click="onUpsertAcl">更新 ACL</NButton>
        <NButton @click="onListAcl">刷新 ACL</NButton>
      </NSpace>
      <NDataTable :columns="aclColumns" :data="aclItems" :pagination="{ pageSize: 6 }" />
    </NCard>

    <NCard title="审计日志">
      <NSpace>
        <NButton type="primary" @click="onLoadAudit">加载最近日志</NButton>
      </NSpace>
      <NDataTable :columns="auditColumns" :data="auditLogs" :pagination="{ pageSize: 8 }" />
    </NCard>

    <NAlert v-if="message" type="success" :show-icon="true">{{ message }}</NAlert>
    <NAlert v-if="errorMessage" type="error" :show-icon="true">{{ errorMessage }}</NAlert>
  </div>
</template>

<script setup lang="ts">
import { h, ref } from "vue";
import {
  NAlert,
  NButton,
  NCard,
  NDataTable,
  NFormItem,
  NGrid,
  NGridItem,
  NInput,
  NSelect,
  NSpace,
  NTag,
  type DataTableColumns,
} from "naive-ui";

import {
  type AuditLogItem,
  type ProjectAclItem,
  getCurrentUser,
  listAuditLogs,
  listProjectAcl,
  login,
  logout,
  registerUser,
  upsertProjectAcl,
} from "@/api/product";
import { useAuthStore } from "@/stores/auth";

const authStore = useAuthStore();

const tenantId = ref("default");
const projectId = ref("default");

const username = ref("demo_user");
const email = ref("demo_user@ainer.ai");
const password = ref("demo_pass");
const userId = ref("");

const aclUserId = ref("");
const aclRole = ref("editor");
const aclItems = ref<ProjectAclItem[]>([]);
const auditLogs = ref<AuditLogItem[]>([]);

const roleOptions = [
  { label: "owner", value: "owner" },
  { label: "admin", value: "admin" },
  { label: "editor", value: "editor" },
  { label: "viewer", value: "viewer" },
];

const message = ref("");
const errorMessage = ref("");

const aclColumns: DataTableColumns<ProjectAclItem> = [
  { title: "User ID", key: "user_id" },
  { title: "Project ID", key: "project_id" },
  {
    title: "Role",
    key: "role",
    render: (row) => h(NTag, { type: "info", bordered: false }, { default: () => row.role }),
  },
];

const auditColumns: DataTableColumns<AuditLogItem> = [
  { title: "Event", key: "event_type" },
  { title: "Producer", key: "producer" },
  { title: "Occurred At", key: "occurred_at" },
  {
    title: "Run/Job",
    key: "run_job",
    render: (row) => `${row.run_id || "-"} / ${row.job_id || "-"}`,
  },
];

function stringifyError(error: unknown): string {
  if (error instanceof Error) {
    return error.message;
  }
  return String(error);
}

function clearNotice(): void {
  message.value = "";
  errorMessage.value = "";
}

async function onRegister(): Promise<void> {
  clearNotice();
  try {
    const data = await registerUser({
      username: username.value,
      email: email.value,
      password: password.value,
    });
    userId.value = data.user_id;
    aclUserId.value = data.user_id;
    message.value = `registered: ${data.user_id}`;
  } catch (error) {
    errorMessage.value = `register failed: ${stringifyError(error)}`;
  }
}

async function onLogin(): Promise<void> {
  clearNotice();
  try {
    const session = await login({ username: email.value, password: password.value });
    authStore.setSession(session.token);
    userId.value = session.user_id;
    aclUserId.value = session.user_id;

    try {
      const profile = await getCurrentUser();
      authStore.setUser(profile);
    } catch {
      authStore.setUser({
        user_id: session.user_id,
        email: email.value,
        display_name: username.value,
      });
    }

    message.value = "login ok";
  } catch (error) {
    errorMessage.value = `login failed: ${stringifyError(error)}`;
  }
}

async function onLogout(): Promise<void> {
  clearNotice();
  try {
    await logout();
    authStore.clearSession();
    message.value = "logout ok";
  } catch (error) {
    errorMessage.value = `logout failed: ${stringifyError(error)}`;
  }
}

async function onUpsertAcl(): Promise<void> {
  clearNotice();
  if (!projectId.value || !tenantId.value || !aclUserId.value) {
    errorMessage.value = "project_id / tenant_id / user_id is required";
    return;
  }
  try {
    await upsertProjectAcl(projectId.value, aclUserId.value, {
      tenant_id: tenantId.value,
      role: aclRole.value,
    });
    await onListAcl();
    message.value = "acl updated";
  } catch (error) {
    errorMessage.value = `upsert acl failed: ${stringifyError(error)}`;
  }
}

async function onListAcl(): Promise<void> {
  clearNotice();
  try {
    aclItems.value = await listProjectAcl(projectId.value, tenantId.value);
  } catch (error) {
    errorMessage.value = `load acl failed: ${stringifyError(error)}`;
  }
}

async function onLoadAudit(): Promise<void> {
  clearNotice();
  try {
    auditLogs.value = await listAuditLogs({
      tenant_id: tenantId.value,
      project_id: projectId.value || undefined,
      limit: 20,
    });
  } catch (error) {
    errorMessage.value = `load audit failed: ${stringifyError(error)}`;
  }
}
</script>
