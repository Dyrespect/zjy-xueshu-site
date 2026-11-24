import { defineConfig, devices } from "@playwright/test";

// 不自动起服务：先 `bash scripts/dev.sh`（或带 BACKEND_PORT / FRONTEND_PORT），再 `pnpm e2e`。
// 浏览器用本机已装的 chromium-1243 / webkit-2359（跟 @playwright/test 1.63.0 配套），不用再下载。
const port = process.env.FRONTEND_PORT ?? "5173";

export default defineConfig({
  testDir: "./e2e",
  outputDir: "./test-results",
  reporter: "list",
  use: { baseURL: `http://127.0.0.1:${port}`, locale: "zh-CN" },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
    { name: "webkit", use: { ...devices["Desktop Safari"] } },
  ],
});
