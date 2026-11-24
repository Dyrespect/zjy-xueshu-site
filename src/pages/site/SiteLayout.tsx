import { Outlet, ScrollRestoration, useLocation } from "react-router";

import { SiteFrame } from "@/blocks/site-shell/load";
import { usePageMeta } from "@/lib/page-meta";
import { sitePage, siteTitle } from "@/lib/site-pages";

/** 官网各页共用的框：同一套页头页脚（页面切换时不重画）、每页的标题和描述（来自 lib/site-pages.ts）、维护中、noindex。 */
export default function SiteLayout() {
  const { pathname } = useLocation();
  const page = sitePage(pathname);
  usePageMeta(siteTitle(page?.title ?? "", pathname), page?.description);
  return (
    <SiteFrame current={pathname} sticky className="text-base">
      <ScrollRestoration />
      <Outlet />
    </SiteFrame>
  );
}
