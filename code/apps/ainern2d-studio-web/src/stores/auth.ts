import { computed, ref } from "vue";
import { defineStore } from "pinia";

export const AUTH_TOKEN_KEY = "ainer_studio_auth_token";
export const AUTH_USER_KEY = "ainer_studio_auth_user";

export interface AuthUserProfile {
  user_id: string;
  email: string;
  display_name: string;
}

function safeReadUser(): AuthUserProfile | null {
  const raw = localStorage.getItem(AUTH_USER_KEY);
  if (!raw) {
    return null;
  }
  try {
    return JSON.parse(raw) as AuthUserProfile;
  } catch {
    localStorage.removeItem(AUTH_USER_KEY);
    return null;
  }
}

export const useAuthStore = defineStore("auth", () => {
  const token = ref(localStorage.getItem(AUTH_TOKEN_KEY) || "");
  const user = ref<AuthUserProfile | null>(safeReadUser());

  const isAuthenticated = computed(() => token.value.length > 0);

  function setSession(nextToken: string, nextUser?: AuthUserProfile | null): void {
    token.value = nextToken;
    localStorage.setItem(AUTH_TOKEN_KEY, nextToken);
    if (nextUser) {
      setUser(nextUser);
    }
  }

  function setUser(nextUser: AuthUserProfile): void {
    user.value = nextUser;
    localStorage.setItem(AUTH_USER_KEY, JSON.stringify(nextUser));
  }

  function clearSession(): void {
    token.value = "";
    user.value = null;
    localStorage.removeItem(AUTH_TOKEN_KEY);
    localStorage.removeItem(AUTH_USER_KEY);
  }

  return {
    token,
    user,
    isAuthenticated,
    setSession,
    setUser,
    clearSession,
  };
});
