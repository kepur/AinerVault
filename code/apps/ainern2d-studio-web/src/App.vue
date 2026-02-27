<template>
  <NConfigProvider :theme-overrides="themeOverrides">
    <NMessageProvider>
      <template v-if="isPublicRoute">
        <RouterView />
      </template>

      <template v-else>
        <NLayout has-sider class="admin-layout">
          <NLayoutSider
            v-model:collapsed="collapsed"
            bordered
            collapse-mode="width"
            :collapsed-width="72"
            :width="250"
            show-trigger
          >
            <div class="brand-block">
              <div class="brand-title">Ainer Studio</div>
              <div class="brand-subtitle">Admin Console</div>
            </div>
            <NMenu
              :value="activeMenuKey"
              :expanded-keys="expandedKeys"
              :options="menuOptions"
              :collapsed="collapsed"
              :collapsed-width="72"
              :collapsed-icon-size="18"
              @update:value="onMenuSelect"
              @update:expanded-keys="onExpandedKeysUpdate"
            />
          </NLayoutSider>

          <NLayout>
            <NLayoutHeader bordered class="admin-header">
              <NBreadcrumb>
                <NBreadcrumbItem v-for="item in breadcrumbItems" :key="item.path">
                  {{ item.title }}
                </NBreadcrumbItem>
              </NBreadcrumb>
              <NSpace align="center" :size="12">
                <NTag type="info" :bordered="false">{{ userLabel }}</NTag>
                <NButton quaternary @click="onLogout">退出登录</NButton>
              </NSpace>
            </NLayoutHeader>

            <NLayoutContent class="admin-content">
              <RouterView />
            </NLayoutContent>
          </NLayout>
        </NLayout>
      </template>
    </NMessageProvider>
  </NConfigProvider>
</template>

<script setup lang="ts">
import { computed, ref } from "vue";
import {
  NBreadcrumb,
  NBreadcrumbItem,
  NButton,
  NConfigProvider,
  NLayout,
  NLayoutContent,
  NLayoutHeader,
  NLayoutSider,
  NMenu,
  NMessageProvider,
  NSpace,
  NTag,
  type MenuOption,
} from "naive-ui";
import { useRoute, useRouter } from "vue-router";

import { logout } from "@/api/product";
import { useAuthStore } from "@/stores/auth";

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();

const collapsed = ref(false);
const expandedKeys = ref<string[]>([
  "group-overview",
  "group-auth",
  "group-roles",
  "group-content",
  "group-config",
  "group-assets",
]);

const menuOptions: MenuOption[] = [
  {
    key: "group-overview",
    label: "总览",
    children: [
      {
        key: "/dashboard",
        label: "控制台",
      },
    ],
  },
  {
    key: "group-auth",
    label: "23 账号权限",
    children: [
      {
        key: "/studio/auth/users",
        label: "23 账号与权限",
      },
    ],
  },
  {
    key: "group-roles",
    label: "角色能力中台",
    children: [
      {
        key: "/studio/roles",
        label: "Role Studio",
      },
    ],
  },
  {
    key: "group-content",
    label: "24/28 内容任务",
    children: [
      {
        key: "/studio/chapters",
        label: "24 章节管理",
      },
      {
        key: "/studio/runs",
        label: "28 任务运行中心",
      },
    ],
  },
  {
    key: "group-config",
    label: "25/26/27 配置资源",
    children: [
      {
        key: "/studio/providers",
        label: "25 Provider路由",
      },
      {
        key: "/studio/languages",
        label: "25 多语言设置",
      },
      {
        key: "/studio/rag",
        label: "26 RAG与导演",
      },
      {
        key: "/studio/culture",
        label: "27 文化包管理",
      },
    ],
  },
  {
    key: "group-assets",
    label: "29/30 素材时间线",
    children: [
      {
        key: "/studio/assets",
        label: "29 素材库",
      },
      {
        key: "/studio/asset-bindings",
        label: "29 素材绑定一致性",
      },
      {
        key: "/studio/timeline",
        label: "30 PR时间线编辑",
      },
    ],
  },
];

const themeOverrides = {
  common: {
    fontFamily: '"IBM Plex Sans", "Segoe UI", sans-serif',
    primaryColor: "#0f766e",
    primaryColorHover: "#0d9488",
    primaryColorPressed: "#115e59",
    borderRadius: "8px",
  },
};

const isPublicRoute = computed(() => Boolean(route.meta.public));

const activeMenuKey = computed(() => {
  if (route.path.startsWith("/studio/")) {
    return route.path;
  }
  if (route.path.includes("/preview") || route.path.includes("/voice")) {
    return "/studio/timeline";
  }
  return "/dashboard";
});

const userLabel = computed(() => {
  if (authStore.user?.display_name) {
    return authStore.user.display_name;
  }
  if (authStore.user?.email) {
    return authStore.user.email;
  }
  return "未命名用户";
});

const breadcrumbItems = computed(() =>
  route.matched
    .filter((record) => typeof record.meta.title === "string")
    .map((record) => ({
      path: record.path,
      title: record.meta.title as string,
    }))
);

function onMenuSelect(key: string): void {
  if (key.startsWith("/")) {
    void router.push(key);
  }
}

function onExpandedKeysUpdate(keys: Array<string | number>): void {
  expandedKeys.value = keys.map((key) => String(key));
}

async function onLogout(): Promise<void> {
  try {
    await logout();
  } finally {
    authStore.clearSession();
    await router.replace("/login");
  }
}
</script>
