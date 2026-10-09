import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

// 构建产物由 ainer-core 在 /studio 下提供（见 app/main.py），所以 base 必须是 /studio/。
// 开发时 vite 自己起在 5174，/api 与 /media 转给本机的 core。
// 开发时 /api 与 /media 转给 core。CORE_URL 可以指到另一个实例（例如长任务跑着、不能重启 8100 时）
const core = process.env.CORE_URL ?? "http://127.0.0.1:8100";

const trailingSlashRedirect: Plugin = {
  name: "trailing-slash-redirect",
  configureServer(server) {
    server.middlewares.use((req, res, next) => {
      const url = req.url || "";
      if (url === "/studio" || url.startsWith("/studio?")) {
        const dest = url.replace(/^\/studio(\?.*)?$/, "/studio/$1");
        res.writeHead(302, { Location: dest });
        res.end();
        return;
      }
      next();
    });
  },
};

export default defineConfig({
  base: "/studio/",
  plugins: [react(), trailingSlashRedirect],
  server: {
    port: 5174,
    proxy: {
      "/api": core,
      "/media": core,
      // 顶栏「后台 ↗」、健康检查、接口文档：5174 上也能直接点开
      "/admin": core,
      "/health": core,
      "/docs": core,
      "/openapi.json": core,
    },
  },
});

