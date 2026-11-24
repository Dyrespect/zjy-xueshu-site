import { lazy, Suspense, type ComponentProps, type ComponentType } from "react";

/**
 * 按路由懒加载页面：页面代码单独打一个包，进到这一页才下载（图库首页的首屏包就不带后台、聊天、交付页）。
 * 用法（routes.tsx）：
 *   const OrdersPage = lazyPage(() => import("./OrdersPage").then((m) => ({ default: m.OrdersPage })));
 *   { path: "orders", element: <OrdersPage /> }
 * 包还没下载完时什么都不画（一般几十毫秒），不闪加载动画。
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any -- 页面组件的 props 各不相同
export function lazyPage<C extends ComponentType<any>>(load: () => Promise<{ default: C }>) {
  const Page = lazy(load);
  return function LazyPage(props: ComponentProps<C>) {
    return (
      <Suspense fallback={null}>
        <Page {...props} />
      </Suspense>
    );
  };
}
