import axios from "axios";

import { AUTH_TOKEN_KEY, AUTH_USER_KEY } from "@/stores/auth";

const apiBase = import.meta.env.VITE_API_BASE_URL || "";

export const http = axios.create({
  baseURL: apiBase,
  timeout: 15000,
});

interface StructuredApiError {
  error_code?: string;
  message?: string;
  error?: {
    error_code?: string;
    message?: string;
  };
}

function parseApiErrorMessage(payload: unknown, status: number): string {
  const data = payload as StructuredApiError | undefined;
  const code = data?.error?.error_code || data?.error_code;
  const message = data?.error?.message || data?.message;
  if (code && message) {
    return `[${code}] ${message}`;
  }
  if (message) {
    return message;
  }
  return `request failed (${status})`;
}

http.interceptors.request.use((config) => {
  const token = localStorage.getItem(AUTH_TOKEN_KEY);
  if (token) {
    config.headers = config.headers || {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

http.interceptors.response.use(
  (response) => response,
  async (error) => {
    const status = error?.response?.status as number | undefined;
    if (status === 401) {
      localStorage.removeItem(AUTH_TOKEN_KEY);
      localStorage.removeItem(AUTH_USER_KEY);
      if (window.location.pathname !== "/login") {
        const redirect = encodeURIComponent(`${window.location.pathname}${window.location.search}`);
        window.location.href = `/login?redirect=${redirect}`;
      }
    }
    if (status) {
      const wrapped = new Error(parseApiErrorMessage(error?.response?.data, status));
      return Promise.reject(wrapped);
    }
    return Promise.reject(error instanceof Error ? error : new Error(String(error)));
  }
);
