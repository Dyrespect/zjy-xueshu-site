import { lazy, Suspense } from "react";
import { createBrowserRouter, RouterProvider, type RouteObject } from "react-router";

import { Toaster } from "@/components/ui/sonner";
import NotFound from "@/pages/NotFound";
import { ErrorPage } from "@/pages/site/ErrorPage";

/**
 * 路由自动收集，一般不用改这个文件：
 * 每块业务在 src/pages/<区域>/routes.tsx 默认导出一个 RouteObject[]（可以带嵌套的 layout），
 * 这里用 import.meta.glob 全部收进来。图库、接单、后台各写各的 routes.tsx，并行开发不会改到同一个文件。
 * React Router 按路径具体程度匹配，跟数组顺序无关。
 */
type RouteModule = { default: RouteObject[] };

const pageRoutes: RouteObject[] = Object.values(
  import.meta.glob<RouteModule>("./pages/**/routes.tsx", { eager: true }),
).flatMap((m) => m.default);

// 只在开发时挂：生产构建里 import.meta.env.DEV 是 false，这段连同 DevBlocks 的代码一起被去掉
const DevBlocks = import.meta.env.DEV ? lazy(() => import("@/pages/DevBlocks")) : null;
const devRoutes: RouteObject[] = DevBlocks
  ? [
      {
        path: "/dev/blocks",
        element: (
          <Suspense fallback={null}>
            <DevBlocks />
          </Suspense>
        ),
      },
    ]
  : [];

// 不在这里包全局 TooltipProvider：Tooltip 自己带（components/ui/tooltip.tsx），
// 这样提示框的代码只进用到它的页面的包，图库首页首屏少下 14 KB（gzip）。
// 最外层包一层只为挂出错页：任何一页的代码出错、懒加载的包下不来（刚发新版时常见），都显示同一个出错页（pages/site/ErrorPage.tsx）
const router = createBrowserRouter([
  { errorElement: <ErrorPage />, children: [...pageRoutes, ...devRoutes, { path: "*", element: <NotFound /> }] },
]);

export default function App() {
  return (
    <>
      <RouterProvider router={router} />
      <Toaster position="top-center" />
    </>
  );
}
