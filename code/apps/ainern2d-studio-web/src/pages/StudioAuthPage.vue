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

    <!-- User Management Table -->
    <NCard :title="t('auth.title')">
      <NSpace align="center" style="margin-bottom: 16px;">
        <NButton type="primary" @click="onLoadUsers">刷新用户列表</NButton>
        <NButton type="success" @click="showAddDrawer = true">➕ 新增用户</NButton>
        <NButton type="warning" @click="onInitPermissions">初始化默认权限</NButton>
      </NSpace>
      <NDataTable :columns="userColumns" :data="userList" :pagination="{ pageSize: 8 }" style="margin-top: 12px" />

      <NDrawer v-model:show="showAddDrawer" :width="400" placement="right">
        <NDrawerContent :title="t('auth.newUser')">
          <NFormItem label="邮箱 (登录名)">
            <NInput v-model:value="addEmail" placeholder="user@ainer.ai" />
          </NFormItem>
          <NFormItem label="显示名称">
            <NInput v-model:value="addDisplayName" placeholder="Ainer User" />
          </NFormItem>
          <NFormItem label="初始密码 (至少6位)">
            <NInput v-model:value="addPassword" type="password" show-password-on="click" />
          </NFormItem>
          <NFormItem label="角色">
            <NSelect v-model:value="addRole" :options="roleOptions" />
          </NFormItem>
          <NFormItem label="Telegram 配置 (可选接收通知)">
            <NInput v-model:value="addTgChatId" placeholder="chat_id" />
          </NFormItem>
          <NSpace>
            <NButton type="primary" @click="onAddUser">{{ t('common.create') }}</NButton>
            <NButton @click="showAddDrawer = false">{{ t('common.cancel') }}</NButton>
          </NSpace>
        </NDrawerContent>
      </NDrawer>

      <!-- Edit Drawer -->
      <NDrawer v-model:show="showEditDrawer" :width="400" placement="right">
        <NDrawerContent :title="t('auth.editUser')">
          <NFormItem label="Display Name">
            <NInput v-model:value="editDisplayName" />
          </NFormItem>
          <NFormItem label="Role">
            <NSelect v-model:value="editRole" :options="roleOptions" />
          </NFormItem>
          <NSpace>
            <NButton type="primary" @click="onSaveUser">{{ t('common.save') }}</NButton>
            <NButton @click="showEditDrawer = false">{{ t('common.cancel') }}</NButton>
          </NSpace>
          <NDivider />
          <NFormItem label="重置密码（新密码）">
            <NInput v-model:value="newPassword" type="password" show-password-on="click" />
          </NFormItem>
          <NButton type="error" :disabled="!newPassword" @click="onResetPassword">重置密码</NButton>
        </NDrawerContent>
      </NDrawer>
    </NCard>

    <!-- Route Permissions Table -->
    <NCard :title="t('auth.permRules')">
      <NDataTable :columns="permissionColumns" :data="permissionsList" :pagination="{ pageSize: 10 }" />
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
  NDivider,
  NDrawer,
  NDrawerContent,
  NFormItem,
  NGrid,
  NGridItem,
  NInput,
  NPopconfirm,
  NSelect,
  NSpace,
  NTag,
  type DataTableColumns,
} from "naive-ui";
import { useI18n } from "@/composables/useI18n";


import {
  type AuditLogItem,
  type ProjectAclItem,
  type UserListItem,
  deleteUser,
  getCurrentUser,
  initPermissions,
  listAuditLogs,
  listProjectAcl,
  listUsers,
  adminCreateUser,
  resetUserPassword,
  updateUser,
  upsertProjectAcl,
} from "@/api/product";
import { useAuthStore } from "@/stores/auth";

const { t } = useI18n();

const authStore = useAuthStore();

const tenantId = ref("default");
const projectId = ref("default");

const aclUserId = ref("");
const aclRole = ref("editor");
const aclItems = ref<ProjectAclItem[]>([]);
const auditLogs = ref<AuditLogItem[]>([]);

const userList = ref<UserListItem[]>([]);
const showEditDrawer = ref(false);
const editUserId = ref("");
const editDisplayName = ref("");
const editRole = ref("viewer");
const newPassword = ref("");

const showAddDrawer = ref(false);
const addEmail = ref("");
const addDisplayName = ref("");
const addPassword = ref("");
const addRole = ref("editor");
const addTgChatId = ref("");

const permissionsList = ref([
  { path_prefix: "/api/v1/auth/users", method: "*", required_role: "admin" },
  { path_prefix: "/api/v1/config/", method: "*", required_role: "admin" },
  { path_prefix: "/api/v1/novels", method: "POST/PUT/DELETE", required_role: "editor" },
  { path_prefix: "/api/v1/rag/", method: "POST", required_role: "editor" },
  { path_prefix: "/api/v1/culture-packs/", method: "POST/DELETE", required_role: "editor" },
]);

const roleOptions = [
  { label: "owner", value: "owner" },
  { label: "admin", value: "admin" },
  { label: "editor", value: "editor" },
  { label: "viewer", value: "viewer" },
];

const message = ref("");
const errorMessage = ref("");

const userColumns: DataTableColumns<UserListItem> = [
  { title: "Email", key: "email" },
  { title: "Display Name", key: "display_name" },
  {
    title: "Role",
    key: "role",
    render: (row: UserListItem) => h(NTag, { type: "info", bordered: false }, { default: () => row.role }),
  },
  { title: "Created At", key: "created_at", render: (row: UserListItem) => row.created_at ? new Date(row.created_at).toLocaleDateString() : "-" },
  {
    title: "Actions",
    key: "actions",
    render: (row: UserListItem) =>
      h(NSpace, {}, {
        default: () => [
          h(NButton, {
            size: "small",
            type: "primary",
            onClick: () => openEditDrawer(row),
          }, { default: () => "编辑" }),
          h(NPopconfirm, {
            onPositiveClick: () => onDeleteUser(row.id),
          }, {
            trigger: () => h(NButton, { size: "small", type: "error" }, { default: () => "删除" }),
            default: () => `确认删除用户 ${row.email}?`,
          }),
        ],
      }),
  },
];

const aclColumns: DataTableColumns<ProjectAclItem> = [
  { title: "User ID", key: "user_id" },
  { title: "Project ID", key: "project_id" },
  {
    title: "Role",
    key: "role",
    render: (row: UserListItem) => h(NTag, { type: "info", bordered: false }, { default: () => row.role }),
  },
];

const auditColumns: DataTableColumns<AuditLogItem> = [
  { title: "Event", key: "event_type" },
  { title: "Producer", key: "producer" },
  { title: "Occurred At", key: "occurred_at" },
  {
    title: "Run/Job",
    key: "run_job",
    render: (row: AuditLogItem) => `${row.run_id || "-"} / ${row.job_id || "-"}`,
  },
];

const permissionColumns = [
  { title: "Path Prefix", key: "path_prefix" },
  { title: "Method", key: "method" },
  { title: "Required Role", key: "required_role", render: (row: { required_role: string }) => h(NTag, { type: "warning", bordered: false }, { default: () => row.required_role }) },
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

function openEditDrawer(user: UserListItem): void {
  editUserId.value = user.id;
  editDisplayName.value = user.display_name;
  editRole.value = user.role;
  newPassword.value = "";
  showEditDrawer.value = true;
}

async function onAddUser(): Promise<void> {
  clearNotice();
  try {
    const data = await adminCreateUser({
      email: addEmail.value,
      display_name: addDisplayName.value,
      password: addPassword.value,
      role: addRole.value,
      tg_chat_id: addTgChatId.value || undefined,
    });
    showAddDrawer.value = false;
    message.value = `用户创建成功: ${data.user_id}`;
    addEmail.value = "";
    addDisplayName.value = "";
    addPassword.value = "";
    addTgChatId.value = "";
    await onLoadUsers();
  } catch (error) {
    errorMessage.value = `创建用户失败: ${stringifyError(error)}`;
  }
}

async function onLoadUsers(): Promise<void> {
  clearNotice();
  try {
    userList.value = await listUsers(tenantId.value);
    message.value = `loaded ${userList.value.length} users`;
  } catch (error) {
    errorMessage.value = `load users failed: ${stringifyError(error)}`;
  }
}

async function onSaveUser(): Promise<void> {
  clearNotice();
  try {
    await updateUser(
      editUserId.value,
      { display_name: editDisplayName.value, role: editRole.value },
      tenantId.value
    );
    showEditDrawer.value = false;
    await onLoadUsers();
    message.value = "user updated";
  } catch (error) {
    errorMessage.value = `update failed: ${stringifyError(error)}`;
  }
}

async function onDeleteUser(uid: string): Promise<void> {
  clearNotice();
  try {
    await deleteUser(uid, tenantId.value);
    await onLoadUsers();
    message.value = "user deleted";
  } catch (error) {
    errorMessage.value = `delete failed: ${stringifyError(error)}`;
  }
}

async function onResetPassword(): Promise<void> {
  clearNotice();
  try {
    await resetUserPassword(editUserId.value, newPassword.value, tenantId.value);
    newPassword.value = "";
    message.value = "password reset ok";
  } catch (error) {
    errorMessage.value = `reset password failed: ${stringifyError(error)}`;
  }
}

async function onInitPermissions(): Promise<void> {
  clearNotice();
  try {
    const result = await initPermissions(tenantId.value, projectId.value);
    message.value = `permissions initialized: ${result.permissions_written} written`;
  } catch (error) {
    errorMessage.value = `init permissions failed: ${stringifyError(error)}`;
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
