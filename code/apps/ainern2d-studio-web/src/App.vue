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
              <NSpace align="center" :size="8">
                <NTag type="info" :bordered="false">{{ userLabel }}</NTag>

                <!-- 🌐 Language switcher -->
                <NDropdown
                  :options="localeOptions"
                  @select="onLocaleSelect"
                  trigger="click"
                >
                  <NButton quaternary size="small" style="font-size:18px;padding:0 8px">🌐</NButton>
                </NDropdown>

                <!-- 🔑 Reset password -->
                <NButton quaternary size="small" @click="showPwdModal = true" style="font-size:16px;padding:0 8px">🔑</NButton>

                <!-- 退出 -->
                <NButton quaternary @click="onLogout">{{ t.logout }}</NButton>
              </NSpace>

              <!-- Change Password Modal -->
              <NModal v-model:show="showPwdModal" preset="card" :title="t.changePwd" style="width:400px">
                <NForm>
                  <NFormItem :label="t.newPassword">
                    <NInput
                      v-model:value="newPassword"
                      type="password"
                      show-password-on="click"
                      :placeholder="t.pwdPlaceholder"
                    />
                  </NFormItem>
                  <NFormItem :label="t.confirmPassword">
                    <NInput
                      v-model:value="confirmPassword"
                      type="password"
                      show-password-on="click"
                      :placeholder="t.confirmPlaceholder"
                    />
                  </NFormItem>
                </NForm>
                <template #footer>
                  <NSpace justify="end">
                    <NButton @click="showPwdModal = false">{{ t.cancel }}</NButton>
                    <NButton type="primary" :loading="pwdLoading" @click="onResetPassword">{{ t.confirm }}</NButton>
                  </NSpace>
                </template>
              </NModal>
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
  NDropdown,
  NForm,
  NFormItem,
  NInput,
  NLayout,
  NLayoutContent,
  NLayoutHeader,
  NLayoutSider,
  NMenu,
  NMessageProvider,
  NModal,
  NSpace,
  NTag,
  createDiscreteApi,
  type MenuOption,
} from "naive-ui";
import { useRoute, useRouter } from "vue-router";

import { logout } from "@/api/product";
import { useAuthStore } from "@/stores/auth";
import { useLocaleStore } from "@/stores/locale";

const route = useRoute();
const router = useRouter();
const authStore = useAuthStore();

// createDiscreteApi works outside NMessageProvider context (safe at root level)
const { message } = createDiscreteApi(['message']);

const localeStore = useLocaleStore();
const locale = computed(() => localeStore.locale);

// ─── Language switcher ──────────────────────────────────────────────────────
const localeOptions = [
  { label: '🇨🇳 简体中文', key: 'zh-CN' },
  { label: '🇺🇸 English',   key: 'en-US' },
  { label: '🇯🇵 日本語',    key: 'ja-JP' },
  { label: '🇪🇸 Español',   key: 'es-ES' },
  { label: '🇸🇦 العربية',  key: 'ar-SA' },
];
function onLocaleSelect(key: string) {
  localeStore.setLocale(key as import('@/stores/locale').SupportedLocale);
}

// ─── Reset password modal ───────────────────────────────────────────────────
const showPwdModal = ref(false);
const newPassword  = ref('');
const confirmPassword = ref('');
const pwdLoading  = ref(false);

async function onResetPassword() {
  const np = newPassword.value.trim();
  const cp = confirmPassword.value.trim();
  if (!np || np.length < 6) {
    message.error(t.value.pwdMinLen);
    return;
  }
  if (np !== cp) {
    message.error(t.value.pwdMismatch);
    return;
  }
  const userId = authStore.user?.user_id;
  if (!userId) {
    message.error('No user session');
    return;
  }
  pwdLoading.value = true;
  try {
    const res = await fetch(`/api/v1/auth/users/${userId}/reset-password`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${authStore.token}` },
      body: JSON.stringify({ new_password: np }),
    });
    if (!res.ok) throw new Error(await res.text());
    message.success(t.value.pwdSuccess);
    showPwdModal.value = false;
    newPassword.value = '';
    confirmPassword.value = '';
  } catch (e: unknown) {
    message.error(String(e));
  } finally {
    pwdLoading.value = false;
  }
}

const collapsed = ref(false);
const expandedKeys = ref<string[]>([
  "group-overview",
  "group-models",
  "group-knowledge",
  "group-production",
  "group-settings",
]);

// ─── Menu labels per locale ───────────────────────────────────────────────────
const MENU_I18N: Record<string, Record<string, string>> = {
  "zh-CN": {
    overview: "总览",
    dashboard: "控制台",
    models: "模型与路由",
    modelAssets: "模型资产管理",
    modelRouting: "AI 路由与策略",
    opsBridge: "开放接口接收",
    languages: "多语言设置",
    knowledge: "知识与资产",
    kbAssets: "知识资产中心",
    culture: "文化包 / 世界观",
    assets: "素材库",
    assetBindings: "素材绑定一致性",
    production: "项目与生产",
    novels: "小说管理",
    rolePerson: "角色与 Persona",
    productionBoard: "Production Board",
    runCenter: "Run 运行中心",
    prTimeline: "PR 时间线 (NLE)",
    translations: "转译工程",
    settings: "系统设置",
    notifications: "通知中心",
    auth: "账号与权限",
    auditLogs: "审计日志",
    logout: "退出登录",
    anonymous: "未命名用户",
    changePwd: "修改密码",
    newPassword: "新密码",
    confirmPassword: "确认密码",
    pwdPlaceholder: "请输入新密码（至少6位）",
    confirmPlaceholder: "再次输入新密码",
    pwdMinLen: "密码至少6位",
    pwdMismatch: "两次密码不一致",
    pwdSuccess: "密码修改成功",
    cancel: "取消",
    confirm: "确认修改",
  },
  "en-US": {
    overview: "Overview",
    dashboard: "Dashboard",
    models: "Models & Routing",
    modelAssets: "Model Assets",
    modelRouting: "AI Routing & Strategy",
    opsBridge: "Open Ingress (Ops Bridge)",
    languages: "Language Settings",
    knowledge: "Knowledge & Assets",
    kbAssets: "KB Asset Center",
    culture: "Culture Pack / Worldview",
    assets: "Asset Library",
    assetBindings: "Asset Binding Consistency",
    production: "Projects & Production",
    novels: "Novel Management",
    rolePerson: "Role & Persona",
    productionBoard: "Production Board",
    runCenter: "Run Center",
    prTimeline: "PR Timeline (NLE)",
    translations: "Translation Projects",
    settings: "System Settings",
    notifications: "Notifications",
    auth: "Accounts & Permissions",
    auditLogs: "Audit Logs",
    logout: "Sign Out",
    anonymous: "Anonymous User",
    changePwd: "Change Password",
    newPassword: "New Password",
    confirmPassword: "Confirm Password",
    pwdPlaceholder: "At least 6 characters",
    confirmPlaceholder: "Re-enter new password",
    pwdMinLen: "Password must be at least 6 characters",
    pwdMismatch: "Passwords do not match",
    pwdSuccess: "Password changed successfully",
    cancel: "Cancel",
    confirm: "Confirm",
  },
  "ja-JP": {
    overview: "概要",
    dashboard: "ダッシュボード",
    models: "モデルとルーティング",
    modelAssets: "モデル資産管理",
    modelRouting: "AIルーティング",
    opsBridge: "外部連携受信",
    languages: "言語設定",
    knowledge: "ナレッジと資産",
    kbAssets: "KBアセットセンター",
    culture: "文化パック / 世界観",
    assets: "アセットライブラリ",
    assetBindings: "アセットバインド整合性",
    production: "プロジェクトと生産",
    novels: "小説管理",
    rolePerson: "ロールとペルソナ",
    productionBoard: "Production Board",
    runCenter: "実行センター",
    prTimeline: "PRタイムライン (NLE)",
    translations: "翻訳プロジェクト",
    settings: "システム設定",
    notifications: "通知センター",
    auth: "アカウントと権限",
    auditLogs: "監査ログ",
    logout: "ログアウト",
    anonymous: "匿名ユーザー",
    changePwd: "パスワード変更",
    newPassword: "新しいパスワード",
    confirmPassword: "パスワード確認",
    pwdPlaceholder: "6文字以上",
    confirmPlaceholder: "再入力してください",
    pwdMinLen: "パスワードは6文字以上必要です",
    pwdMismatch: "パスワードが一致しません",
    pwdSuccess: "パスワードを変更しました",
    cancel: "キャンセル",
    confirm: "変更を確認",
  },
  "es-ES": {
    overview: "Resumen",
    dashboard: "Panel",
    models: "Modelos y Rutas",
    modelAssets: "Activos de Modelos",
    modelRouting: "Estrategia de Rutas IA",
    opsBridge: "Ingreso Abierto",
    languages: "Configuración de Idioma",
    knowledge: "Conocimiento y Activos",
    kbAssets: "Centro de Activos KB",
    culture: "Paquete Cultural / Mundo",
    assets: "Biblioteca de Activos",
    assetBindings: "Consistencia de Activos",
    production: "Proyectos y Producción",
    novels: "Novelas",
    rolePerson: "Rol y Persona",
    productionBoard: "Production Board",
    runCenter: "Centro de Ejecución",
    prTimeline: "Línea de Tiempo PR (NLE)",
    translations: "Proyectos de Traducción",
    settings: "Configuración del Sistema",
    notifications: "Notificaciones",
    auth: "Cuentas y Permisos",
    auditLogs: "Registros de Auditoría",
    logout: "Cerrar Sesión",
    anonymous: "Usuario Anónimo",
    changePwd: "Cambiar Contraseña",
    newPassword: "Nueva Contraseña",
    confirmPassword: "Confirmar Contraseña",
    pwdPlaceholder: "Mínimo 6 caracteres",
    confirmPlaceholder: "Repita la contraseña",
    pwdMinLen: "La contraseña debe tener al menos 6 caracteres",
    pwdMismatch: "Las contraseñas no coinciden",
    pwdSuccess: "Contraseña cambiada correctamente",
    cancel: "Cancelar",
    confirm: "Confirmar",
  },
  "ar-SA": {
    overview: "نظرة عامة",
    dashboard: "لوحة التحكم",
    models: "النماذج والتوجيه",
    modelAssets: "أصول النماذج",
    modelRouting: "استراتيجية توجيه الذكاء",
    opsBridge: "استقبال الواجهات المفتوحة",
    languages: "إعدادات اللغة",
    knowledge: "المعرفة والأصول",
    kbAssets: "مركز الأصول",
    culture: "حزمة الثقافة / العالم",
    assets: "مكتبة الأصول",
    assetBindings: "تناسق الأصول",
    production: "المشاريع والإنتاج",
    novels: "إدارة الروايات",
    rolePerson: "الدور والشخصية",
    productionBoard: "Production Board",
    runCenter: "مركز التشغيل",
    prTimeline: "الجدول الزمني PR",
    translations: "مشاريع الترجمة",
    settings: "إعدادات النظام",
    notifications: "الإشعارات",
    auth: "الحسابات والأذونات",
    auditLogs: "سجلات التدقيق",
    logout: "تسجيل الخروج",
    anonymous: "مستخدم مجهول",
    changePwd: "تغيير كلمة المرور",
    newPassword: "كلمة المرور الجديدة",
    confirmPassword: "تأكيد كلمة المرور",
    pwdPlaceholder: "6 أحرف على الأقل",
    confirmPlaceholder: "أعد إدخال كلمة المرور",
    pwdMinLen: "يجب أن تكون كلمة المرور 6 أحرف على الأقل",
    pwdMismatch: "كلمتا المرور غير متطابقتين",
    pwdSuccess: "تم تغيير كلمة المرور بنجاح",
    cancel: "إلغاء",
    confirm: "تأكيد",
  },
};

const t = computed(() => MENU_I18N[locale.value] ?? MENU_I18N["zh-CN"]);

const menuOptions = computed<MenuOption[]>(() => [
  {
    key: "group-overview",
    label: t.value.overview,
    children: [
      { key: "/dashboard", label: t.value.dashboard },
    ],
  },
  {
    key: "group-models",
    label: t.value.models,
    children: [
      { key: "/studio/models-providers", label: t.value.modelAssets },
      { key: "/studio/model-routing", label: t.value.modelRouting },
      { key: "/studio/ops-bridge", label: t.value.opsBridge },
      { key: "/studio/languages", label: t.value.languages },
    ],
  },
  {
    key: "group-knowledge",
    label: t.value.knowledge,
    children: [
      { key: "/studio/kb-assets", label: t.value.kbAssets },
      { key: "/studio/culture", label: t.value.culture },
      { key: "/studio/assets", label: t.value.assets },
      { key: "/studio/asset-bindings", label: t.value.assetBindings },
    ],
  },
  {
    key: "group-production",
    label: t.value.production,
    children: [
      { key: "/studio/novels", label: t.value.novels },
      { key: "/studio/roles/config", label: t.value.rolePerson },
      { key: "/studio/production", label: t.value.productionBoard },
      { key: "/studio/runs", label: t.value.runCenter },
      { key: "/studio/timeline", label: t.value.prTimeline },
      { key: "/studio/translations", label: t.value.translations },
    ],
  },
  {
    key: "group-settings",
    label: t.value.settings,
    children: [
      { key: "/studio/settings/notifications", label: t.value.notifications },
      { key: "/studio/auth/users", label: t.value.auth },
      { key: "/studio/audit-logs", label: t.value.auditLogs },
    ],
  },
]);

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
  if (route.path.startsWith("/studio/translations/")) {
    return "/studio/translations";
  }
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
  return t.value.anonymous;
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
