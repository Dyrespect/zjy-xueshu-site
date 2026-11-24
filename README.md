# 学术汇报平台

心理学学术汇报 PPT 定制平台的代码：官网、下单、图库、后台。从私有仓库导出当前版本（main 07bd03c），不含提交历史、部署文档、数据和图片。

## 前端 `frontend/`
React 18 + Vite + TypeScript + Tailwind v4 + shadcn/ui。技术栈、代码分法、界面规矩见 `frontend/README.md`。

- 官网各页：`frontend/src/pages/site/`（首页 `HomePage.tsx`，文案和样张数据在 `content.ts`、`samples.ts`、`catalog.ts`）
- 官网组件：`frontend/src/blocks/site-*`；页面清单：`frontend/src/lib/site-pages.ts`
- 官网图片（`public/site-assets/`）不在仓库里

## 后端 `backend/`
Python（FastAPI + SQLAlchemy + Alembic），依赖见 `backend/pyproject.toml`、`requirements.lock`。

- `app/website/` 官网设置、robots、下单前同意留痕
- `app/intake/` 接单与接待机器人（小鱼）
- `app/shop/` 商品、下单、支付；`app/invoices/` 发票；`app/delivery/` 交付
- `app/figures/`、`app/gather/` 科研绘图图库
- `app/admin/` 后台接口；`app/channels/`、`app/platforms/` 各接单渠道
- `tests/` 测试

前端开发时 `/api` 代理到后端（默认 `127.0.0.1:8710`）。

## 接口文档 `docs/`
- `docs/openapi.json`：全部 219 个接口的 OpenAPI 3 描述（路径、参数、请求和返回结构），由后端 FastAPI 导出
- `docs/接口清单.md`：同一份内容的简表，按模块列「方法 路径 — 说明」，先看这个
- 数据库：表结构在各模块的 `backend/app/*/models.py`，迁移脚本在 `backend/alembic/versions/`；数据不公开
