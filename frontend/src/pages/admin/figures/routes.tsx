import { Navigate, type RouteObject } from "react-router";

import { lazyPage } from "@/lib/lazy-page";

const AdminLayout = lazyPage(() => import("@/blocks/admin-layout").then((m) => ({ default: m.AdminLayout })));
const InboxPage = lazyPage(() => import("./InboxPage"));
const StatsPage = lazyPage(() => import("./StatsPage"));

/**
 * 后台的图库几页：/admin/figures/{feedback,requests,submissions,site,stats}。
 * 外框用后台统一的 AdminLayout（同一个侧栏和登录检查；侧栏菜单在 blocks/admin-layout/nav.ts）。
 * 跟后台其他页一样按路由懒加载。
 */
const routes: RouteObject[] = [
  {
    path: "/admin/figures",
    element: <AdminLayout />,
    children: [
      { index: true, element: <Navigate to="feedback" replace /> },
      { path: "stats", element: <StatsPage /> },
      { path: ":kind", element: <InboxPage /> },
    ],
  },
];

export default routes;
