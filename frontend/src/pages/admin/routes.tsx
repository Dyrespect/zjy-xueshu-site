import { Navigate, type RouteObject } from "react-router";

import { lazyPage } from "@/lib/lazy-page";

// 后台整块按路由懒加载：图库首页、交付页的访客不用下载后台的代码
const AdminLayout = lazyPage(() => import("@/blocks/admin-layout").then((m) => ({ default: m.AdminLayout })));
const AdminLoginPage = lazyPage(() => import("./AdminLoginPage").then((m) => ({ default: m.AdminLoginPage })));
const ConversationsPage = lazyPage(() => import("./ConversationsPage").then((m) => ({ default: m.ConversationsPage })));
const OrdersPage = lazyPage(() => import("./OrdersPage").then((m) => ({ default: m.OrdersPage })));
const SettingsPage = lazyPage(() => import("./SettingsPage").then((m) => ({ default: m.SettingsPage })));
const CodesPage = lazyPage(() => import("./CodesPage").then((m) => ({ default: m.CodesPage })));
const NodesPage = lazyPage(() => import("./NodesPage").then((m) => ({ default: m.NodesPage })));
const ChannelsPage = lazyPage(() => import("./ChannelsPage").then((m) => ({ default: m.ChannelsPage })));
const InvoicesPage = lazyPage(() => import("./InvoicesPage").then((m) => ({ default: m.InvoicesPage })));
const WebsitePage = lazyPage(() => import("./WebsitePage").then((m) => ({ default: m.WebsitePage })));
const EntryPage = lazyPage(() => import("./EntryPage").then((m) => ({ default: m.EntryPage })));

/**
 * 后台。图库的几页（/admin/figures/*）由图库那边在 pages/admin/figures/routes.tsx 里加，
 * 页面外面包一层 <AdminLayout>…</AdminLayout> 就有同一个侧栏和登录检查。
 */
const routes: RouteObject[] = [
  { path: "/admin/login", element: <AdminLoginPage /> },
  {
    path: "/admin",
    element: <AdminLayout />,
    children: [
      { index: true, element: <Navigate to="/admin/conversations" replace /> },
      { path: "conversations", element: <ConversationsPage /> },
      { path: "conversations/:id", element: <ConversationsPage /> },
      { path: "orders", element: <OrdersPage /> },
      { path: "codes", element: <CodesPage /> },
      { path: "settings", element: <SettingsPage /> },
      { path: "nodes", element: <NodesPage /> },
      { path: "channels", element: <ChannelsPage /> },
      { path: "invoices", element: <InvoicesPage /> },
      { path: "website", element: <WebsitePage /> },
      { path: "entry", element: <EntryPage /> },
    ],
  },
];

export default routes;
