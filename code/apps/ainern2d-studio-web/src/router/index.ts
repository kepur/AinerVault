import { createRouter, createWebHistory } from "vue-router";

import DashboardPage from "@/pages/DashboardPage.vue";
import LoginPage from "@/pages/LoginPage.vue";
import RunPreviewPage from "@/pages/RunPreviewPage.vue";
import StudioAssetLibraryPage from "@/pages/StudioAssetLibraryPage.vue";
import StudioAssetBindingConsistencyPage from "@/pages/StudioAssetBindingConsistencyPage.vue";
import StudioAuthPage from "@/pages/StudioAuthPage.vue";
import StudioChapterEditorPage from "@/pages/StudioChapterEditorPage.vue";
import StudioCulturePackPage from "@/pages/StudioCulturePackPage.vue";
import StudioLanguageSettingsPage from "@/pages/StudioLanguageSettingsPage.vue";
import StudioNovelLibraryPage from "@/pages/StudioNovelLibraryPage.vue";
import StudioProviderRouterPage from "@/pages/StudioProviderRouterPage.vue";
import StudioRoleConfigPage from "@/pages/StudioRoleConfigPage.vue";
import StudioRoleStudioPage from "@/pages/StudioRoleStudioPage.vue";
import StudioRunCenterPage from "@/pages/StudioRunCenterPage.vue";

import VoiceBindingPage from "@/pages/VoiceBindingPage.vue";
import StudioAuditLogsPage from "@/pages/StudioAuditLogsPage.vue";
import StudioChapterRevisionPage from "@/pages/StudioChapterRevisionPage.vue";
import StudioRunSnapshotPage from "@/pages/StudioRunSnapshotPage.vue";
import StudioChapterPreviewPage from "@/pages/StudioChapterPreviewPage.vue";
import { AUTH_TOKEN_KEY } from "@/stores/auth";

// Lazy-loaded new pages
const StudioPersonaPage = () => import("@/pages/StudioPersonaPage.vue");
const StudioKnowledgeCenterPage = () => import("@/pages/StudioKnowledgeCenterPage.vue");
const StudioKBAssetCenterPage = () => import("@/pages/StudioKBAssetCenterPage.vue");
const StudioModelCatalogPage = () => import("../pages/StudioModelCatalogPage.vue");
const StudioModelRoutingPage = () => import("../pages/StudioModelRoutingPage.vue");
const StudioModelsAndProvidersPage = () => import("../pages/StudioModelsAndProvidersPage.vue");
const StudioNotificationSettingsPage = () => import("../pages/StudioNotificationSettingsPage.vue");
const StudioNovelDetailPage = () => import("@/pages/StudioNovelDetailPage.vue");
const StudioTranslationProjectPage = () => import("@/pages/StudioTranslationProjectPage.vue");
const StudioNleTimelinePage = () => import("@/pages/StudioNleTimelinePage.vue");

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
      path: "/studio/novels/:novelId/chapters/:chapterId/editor",
      name: "studio-chapter-editor",
      component: StudioChapterEditorPage,
      props: true,
      meta: {
        requiresAuth: true,
        title: "章节编辑",
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
      path: "/studio/models-providers",
      name: "studio-models-providers",
      component: StudioModelsAndProvidersPage,
      meta: {
        requiresAuth: true,
        title: "模型资产管理",
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
      path: "/studio/model-catalog",
      name: "studio-model-catalog",
      component: StudioModelCatalogPage,
      meta: {
        requiresAuth: true,
        title: "模型目录",
        section: "studio",
      },
    },
    {
      path: "/studio/model-routing",
      name: "studio-model-routing",
      component: StudioModelRoutingPage,
      meta: {
        requiresAuth: true,
        title: "AI 自动路由顾问",
        section: "studio",
      },
    },
    {
      path: "/studio/rag",
      redirect: "/studio/kb-assets",
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
      component: StudioNleTimelinePage,
      meta: {
        requiresAuth: true,
        title: "PR时间线编辑 (NLE)",
        section: "studio",
      },
    },
    {
      path: "/studio/audit-logs",
      name: "studio-audit-logs",
      component: StudioAuditLogsPage,
      meta: {
        requiresAuth: true,
        title: "审计日志",
        section: "studio",
      },
    },
    {
      path: "/studio/novels/:novelId/chapters/:chapterId/revisions",
      name: "studio-chapter-revisions",
      component: StudioChapterRevisionPage,
      props: true,
      meta: {
        requiresAuth: true,
        title: "章节修订历史",
        section: "studio",
      },
    },
    {
      path: "/studio/runs/:runId/snapshot",
      name: "studio-run-snapshot",
      component: StudioRunSnapshotPage,
      props: true,
      meta: {
        requiresAuth: true,
        title: "运行配置快照",
        section: "studio",
      },
    },
    {
      path: "/studio/novels/:novelId/chapters/:chapterId/preview",
      name: "studio-chapter-preview",
      component: StudioChapterPreviewPage,
      props: true,
      meta: {
        requiresAuth: true,
        title: "章节预览规划",
        section: "studio",
      },
    },
    {
      path: "/studio/persona",
      name: "studio-persona",
      component: StudioPersonaPage,
      meta: {
        requiresAuth: true,
        title: "人员 Persona 库",
        section: "studio",
      },
    },
    {
      path: "/studio/knowledge-center",
      name: "studio-knowledge-center",
      component: StudioKnowledgeCenterPage,
      meta: {
        requiresAuth: true,
        title: "知识资产中心",
        section: "studio",
      },
    },
    {
      path: "/studio/kb-assets",
      name: "studio-kb-assets",
      component: StudioKBAssetCenterPage,
      meta: {
        requiresAuth: true,
        title: "KB 资产中心",
        section: "studio",
      },
    },
    {
      path: "/studio/novels/:novelId",
      name: "studio-novel-detail",
      component: StudioNovelDetailPage,
      props: true,
      meta: {
        requiresAuth: true,
        title: "小说详情",
        section: "studio",
      },
    },
    {
      path: "/studio/translations/:projectId",
      name: "studio-translation-project",
      component: StudioTranslationProjectPage,
      props: true,
      meta: {
        requiresAuth: true,
        title: "转译工作台",
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
      path: "/studio/providers",
      redirect: "/studio/models-providers",
    },
    {
      path: "/studio/model-catalog",
      redirect: "/studio/models-providers",
    },
    {
      path: "/studio/chapters",
      redirect: "/studio/novels",
    },
    {
      path: "/studio/chapters/workspace",
      redirect: "/studio/novels",
    },
    {
      path: "/studio/settings/notifications",
      name: "studio-notifications",
      component: StudioNotificationSettingsPage,
      meta: {
        requiresAuth: true,
        title: "通知中心",
        section: "studio",
      },
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
