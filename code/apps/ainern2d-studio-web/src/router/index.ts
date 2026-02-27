import { createRouter, createWebHistory } from "vue-router";

import DashboardPage from "@/pages/DashboardPage.vue";
import LoginPage from "@/pages/LoginPage.vue";
import RunPreviewPage from "@/pages/RunPreviewPage.vue";
import StudioAssetLibraryPage from "@/pages/StudioAssetLibraryPage.vue";
import StudioAssetBindingConsistencyPage from "@/pages/StudioAssetBindingConsistencyPage.vue";
import StudioAuthPage from "@/pages/StudioAuthPage.vue";
import StudioChapterWorkspacePage from "@/pages/StudioChapterWorkspacePage.vue";
import StudioCulturePackPage from "@/pages/StudioCulturePackPage.vue";
import StudioLanguageSettingsPage from "@/pages/StudioLanguageSettingsPage.vue";
import StudioModelRoutingPage from "@/pages/StudioModelRoutingPage.vue";
import StudioNovelLibraryPage from "@/pages/StudioNovelLibraryPage.vue";
import StudioProviderRouterPage from "@/pages/StudioProviderRouterPage.vue";
import StudioRagPersonaPage from "@/pages/StudioRagPersonaPage.vue";
import StudioRoleConfigPage from "@/pages/StudioRoleConfigPage.vue";
import StudioRoleStudioPage from "@/pages/StudioRoleStudioPage.vue";
import StudioRunCenterPage from "@/pages/StudioRunCenterPage.vue";
import StudioTimelinePatchPage from "@/pages/StudioTimelinePatchPage.vue";
import VoiceBindingPage from "@/pages/VoiceBindingPage.vue";
import { AUTH_TOKEN_KEY } from "@/stores/auth";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      redirect: "/dashboard",
    },
    {
      path: "/login",
      name: "login",
      component: LoginPage,
      meta: {
        public: true,
        title: "登录",
      },
    },
    {
      path: "/dashboard",
      name: "dashboard",
      component: DashboardPage,
      meta: {
        requiresAuth: true,
        title: "控制台",
      },
    },
    {
      path: "/studio/auth/users",
      name: "studio-auth-users",
      component: StudioAuthPage,
      meta: {
        requiresAuth: true,
        title: "账号与权限",
        section: "studio",
      },
    },
    {
      path: "/studio/novels",
      name: "studio-novels",
      component: StudioNovelLibraryPage,
      meta: {
        requiresAuth: true,
        title: "小说管理",
        section: "studio",
      },
    },
    {
      path: "/studio/chapters/workspace",
      name: "studio-chapter-workspace",
      component: StudioChapterWorkspacePage,
      meta: {
        requiresAuth: true,
        title: "章节工作区",
        section: "studio",
      },
    },
    {
      path: "/studio/runs",
      name: "studio-runs",
      component: StudioRunCenterPage,
      meta: {
        requiresAuth: true,
        title: "任务运行中心",
        section: "studio",
      },
    },
    {
      path: "/studio/providers",
      name: "studio-providers",
      component: StudioProviderRouterPage,
      meta: {
        requiresAuth: true,
        title: "Provider接入与通知",
        section: "studio",
      },
    },
    {
      path: "/studio/model-routing",
      name: "studio-model-routing",
      component: StudioModelRoutingPage,
      meta: {
        requiresAuth: true,
        title: "模型档案与路由映射",
        section: "studio",
      },
    },
    {
      path: "/studio/languages",
      name: "studio-languages",
      component: StudioLanguageSettingsPage,
      meta: {
        requiresAuth: true,
        title: "多语言设置",
        section: "studio",
      },
    },
    {
      path: "/studio/roles/config",
      name: "studio-role-config",
      component: StudioRoleConfigPage,
      meta: {
        requiresAuth: true,
        title: "角色配置中心",
        section: "studio",
      },
    },
    {
      path: "/studio/roles",
      name: "studio-roles",
      component: StudioRoleStudioPage,
      meta: {
        requiresAuth: true,
        title: "角色工作台配置",
        section: "studio",
      },
    },
    {
      path: "/studio/rag",
      name: "studio-rag",
      component: StudioRagPersonaPage,
      meta: {
        requiresAuth: true,
        title: "RAG与导演",
        section: "studio",
      },
    },
    {
      path: "/studio/culture",
      name: "studio-culture",
      component: StudioCulturePackPage,
      meta: {
        requiresAuth: true,
        title: "文化包管理",
        section: "studio",
      },
    },
    {
      path: "/studio/assets",
      name: "studio-asset-library",
      component: StudioAssetLibraryPage,
      meta: {
        requiresAuth: true,
        title: "素材库",
        section: "studio",
      },
    },
    {
      path: "/studio/asset-bindings",
      name: "studio-asset-bindings",
      component: StudioAssetBindingConsistencyPage,
      meta: {
        requiresAuth: true,
        title: "素材绑定一致性",
        section: "studio",
      },
    },
    {
      path: "/studio/timeline",
      name: "studio-timeline",
      component: StudioTimelinePatchPage,
      meta: {
        requiresAuth: true,
        title: "PR时间线编辑",
        section: "studio",
      },
    },
    {
      path: "/studio/auth",
      redirect: "/studio/auth/users",
    },
    {
      path: "/studio/content",
      redirect: "/studio/novels",
    },
    {
      path: "/studio/config",
      redirect: "/studio/providers",
    },
    {
      path: "/studio/chapters",
      redirect: "/studio/novels",
    },
    {
      path: "/projects/:projectId/runs/:runId/preview",
      name: "run-preview",
      component: RunPreviewPage,
      props: true,
      meta: {
        requiresAuth: true,
        title: "Run 预览",
        section: "tools",
      },
    },
    {
      path: "/projects/:projectId/entities/:entityId/voice",
      name: "voice-binding",
      component: VoiceBindingPage,
      props: true,
      meta: {
        requiresAuth: true,
        title: "语音绑定",
        section: "tools",
      },
    },
  ],
});

router.beforeEach((to) => {
  const token = localStorage.getItem(AUTH_TOKEN_KEY);
  if (to.name === "login" && token) {
    return { name: "dashboard" };
  }
  if (to.meta.public) {
    return true;
  }
  if (!token) {
    return {
      name: "login",
      query: {
        redirect: to.fullPath,
      },
    };
  }
  return true;
});

export default router;
