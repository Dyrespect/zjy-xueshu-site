import type { RouteObject } from "react-router";

import { lazyPage } from "@/lib/lazy-page";

// 我的订单和登录页（模块 D；12 号设计）：一种登录方式都没开时 /me 显示「页面不存在」
const MyOrdersPage = lazyPage(() => import("./MyOrdersPage").then((m) => ({ default: m.MyOrdersPage })));
const LoginPage = lazyPage(() => import("./LoginPage").then((m) => ({ default: m.LoginPage })));

const routes: RouteObject[] = [
  { path: "/me", element: <MyOrdersPage /> },
  { path: "/login", element: <LoginPage /> },
];

export default routes;
