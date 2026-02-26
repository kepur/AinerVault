import { createRouter, createWebHistory } from "vue-router";

import DashboardPage from "@/pages/DashboardPage.vue";
import RunPreviewPage from "@/pages/RunPreviewPage.vue";
import VoiceBindingPage from "@/pages/VoiceBindingPage.vue";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/",
      name: "dashboard",
      component: DashboardPage,
    },
    {
      path: "/projects/:projectId/runs/:runId/preview",
      name: "run-preview",
      component: RunPreviewPage,
      props: true,
    },
    {
      path: "/projects/:projectId/entities/:entityId/voice",
      name: "voice-binding",
      component: VoiceBindingPage,
      props: true,
    },
  ],
});

export default router;
