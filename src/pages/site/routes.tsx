import { Navigate, type RouteObject } from "react-router";

import { lazyPage } from "@/lib/lazy-page";
import { isFiguresHost } from "@/lib/site-host";

import { HomePage } from "./HomePage";
import SiteLayout from "./SiteLayout";

// 首页跟外框一起进首屏包；其余各页点进去才下载（协议三页带 Markdown 渲染，单独一个包）
const SamplesPage = lazyPage(() => import("./SamplesPage").then((m) => ({ default: m.SamplesPage })));
const PricePage = lazyPage(() => import("./PricePage").then((m) => ({ default: m.PricePage })));
const ServicePage = lazyPage(() => import("./ServicePage").then((m) => ({ default: m.ServicePage })));
const RefundPage = lazyPage(() => import("./RefundPage").then((m) => ({ default: m.RefundPage })));
const AboutPage = lazyPage(() => import("./AboutPage").then((m) => ({ default: m.AboutPage })));
const ContactPage = lazyPage(() => import("./ContactPage").then((m) => ({ default: m.ContactPage })));
const HelpPage = lazyPage(() => import("./HelpPage").then((m) => ({ default: m.HelpPage })));
const ChangelogPage = lazyPage(() => import("./ChangelogPage").then((m) => ({ default: m.ChangelogPage })));
const StatusPage = lazyPage(() => import("./StatusPage").then((m) => ({ default: m.StatusPage })));
const SitemapPage = lazyPage(() => import("./SitemapPage").then((m) => ({ default: m.SitemapPage })));
const LicensePage = lazyPage(() => import("./LicensePage").then((m) => ({ default: m.LicensePage })));
const Terms = lazyPage(() => import("./legal/pages").then((m) => ({ default: m.TermsPage })));
const Privacy = lazyPage(() => import("./legal/pages").then((m) => ({ default: m.PrivacyPage })));
const Disclaimer = lazyPage(() => import("./legal/pages").then((m) => ({ default: m.DisclaimerPage })));

/** 站点根：官网首页；图库单独域名时，那个域名的 / 进图库首页 */
function RootHome() {
  return isFiguresHost() ? <Navigate to="/tuku" replace /> : <HomePage />;
}

/**
 * 官网（psyppt 站）：页面清单在 lib/site-pages.ts（导航、页脚、网站地图、sitemap.xml 都从它来）。
 * /order（下单）、/tuku（科研图库）在各自模块的 routes.tsx 里；这里只挂官网自己的页。
 * 旧的静态站地址（/price.html 这类，已经发给支付宝、微信审核的）跳到新地址。
 */
const routes: RouteObject[] = [
  {
    element: <SiteLayout />,
    children: [
      { path: "/", element: <RootHome /> },
      { path: "/samples", element: <SamplesPage /> },
      { path: "/price", element: <PricePage /> },
      { path: "/service", element: <ServicePage /> },
      { path: "/refund", element: <RefundPage /> },
      { path: "/about", element: <AboutPage /> },
      { path: "/license", element: <LicensePage /> },
      { path: "/contact", element: <ContactPage /> },
      { path: "/help", element: <HelpPage /> },
      { path: "/changelog", element: <ChangelogPage /> },
      { path: "/status", element: <StatusPage /> },
      { path: "/sitemap", element: <SitemapPage /> },
      { path: "/terms", element: <Terms /> },
      { path: "/privacy", element: <Privacy /> },
      { path: "/disclaimer", element: <Disclaimer /> },
    ],
  },
  ...["index", "price", "service", "refund", "about"].map((name) => ({
    path: `/${name}.html`,
    element: <Navigate to={name === "index" ? "/" : `/${name}`} replace />,
  })),
];

export default routes;
