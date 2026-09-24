import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// 构建产物由 ainer-core 在 /studio 下提供（见 app/main.py），所以 base 必须是 /studio/。
// 开发时 vite 自己起在 5174，/api 与 /media 转给本机的 core。
// 开发时 /api 与 /media 转给 core。CORE_URL 可以指到另一个实例（例如长任务跑着、不能重启 8100 时）
const core = process.env.CORE_URL ?? "http://127.0.0.1:8100";

export default defineConfig({
  base: "/studio/",
  plugins: [react()],
  server: {
    port: 5174,
    proxy: {
      "/api": core,
      "/media": core,
    },
  },
});
