import type { RouteObject } from "react-router";

import { lazyPage } from "@/lib/lazy-page";

// 需求卡（09 需求引导）：认领后从兑换页、聊天里点进来，地址 /b/{这单的交付令牌}
const BriefPage = lazyPage(() => import("./BriefPage").then((m) => ({ default: m.BriefPage })));

const routes: RouteObject[] = [{ path: "/b/:token", element: <BriefPage /> }];

export default routes;
