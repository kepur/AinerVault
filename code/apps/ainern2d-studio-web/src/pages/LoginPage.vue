<template>
  <div class="login-shell">
    <NCard class="login-card" :bordered="false">
      <NSpace vertical :size="20">
        <div>
          <NTag type="success" :bordered="false">Ainer Studio</NTag>
          <h1 class="login-title">{{ copy.title }}</h1>
          <p class="login-subtitle">{{ copy.subtitle }}</p>
        </div>

        <NFormItem :label="copy.localeLabel">
          <NSelect v-model:value="locale" :options="localeOptions" />
        </NFormItem>

        <NForm @submit.prevent="onSubmit">
          <NFormItem :label="copy.usernameLabel">
            <NInput v-model:value="form.username" placeholder="demo_user@ainer.ai" />
          </NFormItem>
          <NFormItem :label="copy.passwordLabel">
            <NInput
              v-model:value="form.password"
              type="password"
              show-password-on="click"
              :placeholder="copy.passwordPlaceholder"
            />
          </NFormItem>
          <NButton type="primary" block attr-type="submit" :loading="loading">{{ copy.loginButton }}</NButton>
        </NForm>

        <NAlert v-if="errorMessage" type="error" :show-icon="true">{{ errorMessage }}</NAlert>
      </NSpace>
    </NCard>
  </div>
</template>

<script setup lang="ts">
import { computed, reactive, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { NAlert, NButton, NCard, NForm, NFormItem, NInput, NSelect, NSpace, NTag } from "naive-ui";

import { getCurrentUser, login } from "@/api/product";
import { useAuthStore } from "@/stores/auth";

const router = useRouter();
const route = useRoute();
const authStore = useAuthStore();

const form = reactive({
  username: "demo_user@ainer.ai",
  password: "demo_pass",
});

const LOCALE_KEY = "ainer_studio_locale";
const locale = ref(localStorage.getItem(LOCALE_KEY) || "zh-CN");

const localeOptions = [
  { label: "简体中文", value: "zh-CN" },
  { label: "English", value: "en-US" },
  { label: "日本語", value: "ja-JP" },
  { label: "Español", value: "es-ES" },
  { label: "العربية", value: "ar-SA" },
];

const loginCopyMap: Record<string, {
  title: string;
  subtitle: string;
  localeLabel: string;
  usernameLabel: string;
  passwordLabel: string;
  passwordPlaceholder: string;
  loginButton: string;
  emptyError: string;
  failPrefix: string;
}> = {
  "zh-CN": {
    title: "后台管理登录",
    subtitle: "未登录状态下，所有管理页面均不可操作。",
    localeLabel: "界面语言",
    usernameLabel: "账号（邮箱）",
    passwordLabel: "密码",
    passwordPlaceholder: "输入密码",
    loginButton: "登录",
    emptyError: "请输入账号和密码",
    failPrefix: "登录失败",
  },
  "en-US": {
    title: "Admin Login",
    subtitle: "All management actions require authentication.",
    localeLabel: "Interface Language",
    usernameLabel: "Username (Email)",
    passwordLabel: "Password",
    passwordPlaceholder: "Enter password",
    loginButton: "Sign In",
    emptyError: "Please enter username and password",
    failPrefix: "Login failed",
  },
  "ja-JP": {
    title: "管理ログイン",
    subtitle: "未ログイン状態では管理操作は実行できません。",
    localeLabel: "表示言語",
    usernameLabel: "アカウント（メール）",
    passwordLabel: "パスワード",
    passwordPlaceholder: "パスワードを入力",
    loginButton: "ログイン",
    emptyError: "アカウントとパスワードを入力してください",
    failPrefix: "ログイン失敗",
  },
  "es-ES": {
    title: "Acceso de Administración",
    subtitle: "Sin iniciar sesión no se permiten operaciones administrativas.",
    localeLabel: "Idioma de la interfaz",
    usernameLabel: "Cuenta (correo)",
    passwordLabel: "Contraseña",
    passwordPlaceholder: "Introduce la contraseña",
    loginButton: "Iniciar sesión",
    emptyError: "Introduce usuario y contraseña",
    failPrefix: "Error de inicio de sesión",
  },
  "ar-SA": {
    title: "تسجيل دخول الإدارة",
    subtitle: "لا يمكن تنفيذ أي إجراء إداري قبل تسجيل الدخول.",
    localeLabel: "لغة الواجهة",
    usernameLabel: "الحساب (البريد)",
    passwordLabel: "كلمة المرور",
    passwordPlaceholder: "أدخل كلمة المرور",
    loginButton: "تسجيل الدخول",
    emptyError: "يرجى إدخال الحساب وكلمة المرور",
    failPrefix: "فشل تسجيل الدخول",
  },
};

const copy = computed(() => loginCopyMap[locale.value] ?? loginCopyMap["en-US"]);

const loading = ref(false);
const errorMessage = ref("");

watch(
  locale,
  (value) => {
    localStorage.setItem(LOCALE_KEY, value);
    document.documentElement.lang = value;
  },
  { immediate: true }
);

async function onSubmit(): Promise<void> {
  errorMessage.value = "";
  if (!form.username || !form.password) {
    errorMessage.value = copy.value.emptyError;
    return;
  }
  loading.value = true;
  try {
    const session = await login({
      username: form.username,
      password: form.password,
    });
    authStore.setSession(session.token);

    try {
      const profile = await getCurrentUser();
      authStore.setUser(profile);
    } catch {
      authStore.setUser({
        user_id: session.user_id,
        email: form.username,
        display_name: form.username,
      });
    }

    const redirect = typeof route.query.redirect === "string" ? route.query.redirect : "/dashboard";
    await router.replace(redirect);
  } catch (error) {
    errorMessage.value = `${copy.value.failPrefix}: ${String(error)}`;
    authStore.clearSession();
  } finally {
    loading.value = false;
  }
}
</script>
