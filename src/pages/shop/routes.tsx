import type { RouteObject } from "react-router";

import { lazyPage } from "@/lib/lazy-page";

// 下单、付款、固定链接页按路由懒加载（图库首页不带这些代码）
const OrderPage = lazyPage(() => import("./OrderPage").then((m) => ({ default: m.OrderPage })));
const PayPage = lazyPage(() => import("./PayPage").then((m) => ({ default: m.PayPage })));
const ClaimPage = lazyPage(() => import("./ClaimPage").then((m) => ({ default: m.ClaimPage })));

/**
 * 自有网页下单（模块 B）、平台商品固定链接（模块 C）。
 * 付款页 /order/pay/:token：微信里在这一页调起支付，商户平台「JSAPI 支付授权目录」填它所在的目录
 * https://psyppt.pilipala.zj.cn/order/pay/（精确到最后一级、以 / 结尾；官方「配置JSAPI支付授权目录」4013287088，
 * 只填 /order/ 属于「未配置到最后一级支付目录」，调不起来）。见 docs/任务单/11_手机微信支付_设计.md。
 */
const routes: RouteObject[] = [
  { path: "/order", element: <OrderPage /> },
  { path: "/order/pay/:token", element: <PayPage /> },
  { path: "/x/:token", element: <ClaimPage /> },
  // /c/:code 兑换页归模块 D（pages/redeem/），这里原来的临时落脚页删了
];

export default routes;
