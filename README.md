# 学术汇报平台 · 前端

心理学学术汇报 PPT 定制平台的网页前端（React + Vite + TypeScript），从私有仓库的 `frontend/` 导出，不含后端和提交历史。

- 官网各页：`src/pages/site/`（首页 `HomePage.tsx`，文案和样张数据在 `content.ts`、`samples.ts`、`catalog.ts`）
- 官网用的组件：`src/blocks/site-*`
- 官网页面清单：`src/lib/site-pages.ts`
- 官网图片（`public/site-assets/`）不在仓库里

本地运行：`pnpm install && pnpm dev`（接口要连后端，没有后端时页面会缺数据）。
