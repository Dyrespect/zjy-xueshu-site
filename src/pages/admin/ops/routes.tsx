import type { RouteObject } from "react-router";

import { lazyPage } from "@/lib/lazy-page";

const AdminLayout = lazyPage(() => import("@/blocks/admin-layout").then((m) => ({ default: m.AdminLayout })));
const OpsPage = lazyPage(() => import("./OpsPage").then((m) => ({ default: m.OpsPage })));

/** 后台「运维」：/admin/ops（?tab=errors|backups|report|settings，飞书消息里的链接直接跳到对应页签）。外框用后台统一的 AdminLayout。 */
const routes: RouteObject[] = [
  {
    path: "/admin/ops",
    element: <AdminLayout />,
    children: [{ index: true, element: <OpsPage /> }],
  },
];

export default routes;
