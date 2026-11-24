import type { RouteObject } from "react-router";

import { lazyPage } from "@/lib/lazy-page";

// 交付页按路由懒加载（客户打开交付链接只下交付页要的代码，图库首页也不带它）
const DeliveryPage = lazyPage(() => import("./DeliveryPage").then((m) => ({ default: m.DeliveryPage })));

const routes: RouteObject[] = [{ path: "/d/:token", element: <DeliveryPage /> }];

export default routes;
