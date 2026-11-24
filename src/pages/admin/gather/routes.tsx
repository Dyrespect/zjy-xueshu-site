import type { RouteObject } from "react-router";

import { lazyPage } from "@/lib/lazy-page";

const AdminLayout = lazyPage(() => import("@/blocks/admin-layout").then((m) => ({ default: m.AdminLayout })));
const GatherPage = lazyPage(() => import("./GatherPage"));

/** 后台「聚人」：/admin/gather（模块 L）。外框用后台统一的 AdminLayout。 */
const routes: RouteObject[] = [
  {
    path: "/admin/gather",
    element: <AdminLayout />,
    children: [{ index: true, element: <GatherPage /> }],
  },
];

export default routes;
