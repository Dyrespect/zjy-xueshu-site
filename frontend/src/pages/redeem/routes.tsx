import type { RouteObject } from "react-router";

import { lazyPage } from "@/lib/lazy-page";

// 兑换网页（模块 D）：平台发货内容里的 {站点}/c/{码}（app/intake/platform_texts.py 拼的）；/c 是没带码时手动输入
const RedeemPage = lazyPage(() => import("./RedeemPage").then((m) => ({ default: m.RedeemPage })));

const routes: RouteObject[] = [
  { path: "/c", element: <RedeemPage /> },
  { path: "/c/:code", element: <RedeemPage /> },
];

export default routes;
