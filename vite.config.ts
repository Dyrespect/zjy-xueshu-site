import path from "node:path";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import sitemap from "vite-plugin-sitemap";

import { SITE_PAGES } from "./src/lib/site-pages";

// 端口从环境变量来：骨架默认 8710 / 5173；并行开发的 worktree 各用各的（见 AGENTS.md）
const backendPort = process.env.BACKEND_PORT ?? "8710";
const frontendPort = Number(process.env.FRONTEND_PORT ?? "5173");
// sitemap.xml 里网址的域名（构建时定）；robots.txt 不在这里生成：它跟着后台「公开给搜索引擎」开关走（backend/app/website/router.py）
const siteUrl = process.env.SITE_URL ?? "https://psyppt.pilipala.zj.cn";

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    // 构建时出 dist/sitemap.xml：页面清单就是官网的 lib/site-pages.ts（和页脚、网站地图页同一份）
    sitemap({
      hostname: siteUrl,
      dynamicRoutes: SITE_PAGES.map((p) => p.path).filter((p) => p !== "/"),
      exclude: ["/50x", "/maintenance"],
      generateRobotsTxt: false,
      changefreq: "weekly",
    }),
  ],
  resolve: {
    alias: { "@": path.resolve(import.meta.dirname, "src") },
  },
  server: {
    host: "127.0.0.1",
    port: frontendPort,
    strictPort: true,
    proxy: {
      "/api": { target: `http://127.0.0.1:${backendPort}`, changeOrigin: false },
    },
  },
  preview: { host: "127.0.0.1", port: frontendPort, strictPort: true },
});
