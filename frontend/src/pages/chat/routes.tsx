import type { RouteObject } from "react-router";

import { lazyPage } from "@/lib/lazy-page";

// 网页聊天按路由懒加载（图库首页不带聊天的代码）
const ChatStart = lazyPage(() => import("./WebChat").then((m) => ({ default: m.ChatStart })));
const WebChat = lazyPage(() => import("./WebChat").then((m) => ({ default: m.WebChat })));

const routes: RouteObject[] = [
  { path: "/chat", element: <ChatStart /> },
  { path: "/chat/:key", element: <WebChat /> },
];

export default routes;
