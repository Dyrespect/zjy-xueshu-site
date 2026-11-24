---
last_updated: 2026-11-15
status: active
---

# 前端

React 18 + Vite + TypeScript + Tailwind v4 + shadcn/ui（Radix）+ react-router 7 + lucide-react + sonner。

## 怎么跑
- 装：`pnpm install --frozen-lockfile`（或仓库根 `bash scripts/setup.sh`）
- 开发：仓库根 `bash scripts/dev.sh`（后端 + 前端一起起）；只起前端：`pnpm dev`（`/api` 代理到 `127.0.0.1:$BACKEND_PORT`，默认 8710）
- 类型检查：`pnpm typecheck`；构建：`pnpm build`
- 走查：dev.sh 起着时 `pnpm e2e`（Chromium + WebKit）；截图：`SHOT=../docs/截图/xxx.png pnpm e2e --project=chromium`
- 区块陈列（只在开发时有）：http://127.0.0.1:5173/dev/blocks

## 代码怎么分
```text
src/styles/tokens.css      设计变量：色板 → 语义变量（shadcn 命名）→ Tailwind 类。全站唯一能写色值的地方
src/index.css              引 Tailwind、tokens；基础样式
src/components/ui/         shadcn 基础零件（button、input、card、dialog……）。改它等于改底座
src/components/app-link.tsx  站内走路由、站外新窗口
src/lib/api.ts             唯一发请求的地方：基址 /api，带 cookie，非 2xx 抛 ApiError（中文 message）
src/lib/blocks.ts          区块陈列的约定（defineBlockDemo）
src/blocks/<区块>/         一块一个文件夹：
    Xxx.tsx                  组件，只吃 props，不取数
    example.ts               示例数据：默认导出 defineBlockDemo({...})，自动出现在 /dev/blocks
    load.ts                  （需要取数时）只调 src/lib/api.ts 或 src/lib/<区域>.ts
    index.ts                 对外导出
src/pages/                 页面由区块拼
    <区域>/routes.tsx        默认导出 RouteObject[]，App.tsx 自动收集，不用改 App.tsx
    DevBlocks.tsx            /dev/blocks（生产构建里没有）
    NotFound.tsx             兜底 404
```

## 界面规矩（AGENTS.md 也有）
- **平的近白底**：页面底是白，卡片底 `bg-card`（#F6F8FA）配细边 `border`；不用渐变、不用毛玻璃。
- **标题实心近黑**：`text-foreground`（#1D2129），正文 `text-body`（#3C4048），次要字 `text-muted-foreground`（#80868F）。
- **主按钮实心主色**：`<Button>` 默认就是 `bg-primary`（#1F4E9C）；一屏最多一两处高亮。
- **卡片细边、不加大阴影**：Card 已去掉阴影；弹层（Dialog、Sheet）保留默认阴影。
- **不放 emoji**；图标只用 lucide，**标题前不加装饰图标**。
- **层次靠字号、字重、留白**，不靠颜色块和框；框只给能点的东西。
- 红色 `text-price`（#C0392B）只给价格。
- 示例数据要像真的（「测试」「示例 A」这种字一出现就显得 low）；没做出来的功能不放、不放占位图。
- 颜色只用设计变量对应的类（`bg-primary`、`text-muted-foreground`、`border-border`……）。Tailwind 自带调色板（`gray-500`、`red-600`……）已经关掉，写了也没样式；`#xxxxxx`、`rgb(` 写在 tokens.css 以外的地方 check.py 会报错。缺颜色先在 tokens.css 加变量。
- 只做浅色。`dark:` 只在祖先有 `.dark` 时生效（现在没有），所以 shadcn 零件里的 `dark:` 样式不会混进来。

## 可用的颜色类
`background` `foreground` `body` `card` `popover` `primary` `primary-hover` `secondary` `muted` `muted-foreground` `faint` `accent`（悬停底）`highlight`（荧光笔 / 选中）`price` `destructive` `border` `input` `ring` `overlay`（弹层遮罩），前面加 `bg-` / `text-` / `border-` 用。
