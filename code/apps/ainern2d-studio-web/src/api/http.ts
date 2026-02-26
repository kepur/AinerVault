import axios from "axios";

const apiBase = import.meta.env.VITE_API_BASE_URL || "";

export const http = axios.create({
  baseURL: apiBase,
  timeout: 15000,
});
