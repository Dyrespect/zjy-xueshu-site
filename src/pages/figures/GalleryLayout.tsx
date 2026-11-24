import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Outlet, ScrollRestoration, useLocation } from "react-router";

import { sendRequest } from "@/blocks/request-dialog/load";
import { sendSiteFeedback } from "@/blocks/site-feedback-dialog/load";
import { SiteFooter } from "@/blocks/site-footer";
import { SiteHeader } from "@/blocks/site-header";
import { fetchSite } from "@/lib/figures";
import type { SearchContext, SiteInfo } from "@/lib/figures-types";
import { fetchSiteMap, getUnlock, resendUnlock, sendCta, sendVisit, startUnlock, uploadEvidence } from "@/lib/site";
import type { CtaPlacement, SiteMap, UnlockView } from "@/lib/site-types";
import { firstSource, getVisitor, readLanding } from "@/lib/visitor";

import { GalleryContext, orderHref } from "./gallery-context";

const linkClass = "whitespace-nowrap text-muted-foreground transition-colors hover:text-foreground";

// 三个全站弹层第一次打开时才下载（首页首屏包里不带弹层和它们的表单）；打开过一次就一直挂着，关的时候照常有动画
const RequestDialog = lazy(() => import("@/blocks/request-dialog").then((m) => ({ default: m.RequestDialog })));
const SiteFeedbackDialog = lazy(() => import("@/blocks/site-feedback-dialog").then((m) => ({ default: m.SiteFeedbackDialog })));
const AllLibraryDialog = lazy(() => import("@/blocks/all-library-dialog").then((m) => ({ default: m.AllLibraryDialog })));

/**
 * 图库各页共用的框：统一页头（找图、提需求、投图、要全部图库、做汇报 PPT 看这里）、统一页脚（官网、下单、兑换、图库全连通）、
 * 全站弹层；第一次打开时记一次来访（from、s）。站点地图来自 /api/gather/site（模块 L）。
 */
export default function GalleryLayout() {
  const location = useLocation();
  const [site, setSite] = useState<SiteInfo | null>(null);
  const [map, setMap] = useState<SiteMap | null>(null);
  const [requestCtx, setRequestCtx] = useState<SearchContext | null>(null);
  const [allOpen, setAllOpen] = useState(false);
  const [feedbackOpen, setFeedbackOpen] = useState(false);
  const [used, setUsed] = useState({ request: false, feedback: false, all: false });
  const [unlock, setUnlock] = useState<UnlockView | null>(null);
  const [unlockError, setUnlockError] = useState("");
  const visited = useRef(false);

  useEffect(() => {
    fetchSite().then(setSite, () => setSite(null));
    fetchSiteMap("figures").then(setMap, () => setMap(null));
  }, []);

  useEffect(() => {
    if (visited.current) return; // 一次打开只记一次（来源、转发人的分享码）
    visited.current = true;
    const { src, share } = readLanding(location.search);
    sendVisit({ visitor: getVisitor(), landing: location.pathname + location.search, src, share });
  }, [location.pathname, location.search]);

  const trackCta = useCallback((placement: CtaPlacement, target: "site" | "order") => sendCta(placement, target, getVisitor()), []);
  const openRequest = useCallback((ctx?: SearchContext) => {
    setUsed((u) => (u.request ? u : { ...u, request: true }));
    setRequestCtx(ctx ?? { searchId: null, query: "" });
  }, []);
  const openAllLibrary = useCallback(() => {
    setUsed((u) => (u.all ? u : { ...u, all: true }));
    setAllOpen(true);
    setUnlockError("");
    const load = unlock ? getUnlock(unlock.share_code, getVisitor()) : startUnlock(getVisitor(), firstSource());
    load.then(setUnlock, (e: Error) => setUnlockError(e.message || "暂时打不开，过一会儿再试"));
  }, [unlock]);
  const openFeedback = useCallback(() => {
    setUsed((u) => (u.feedback ? u : { ...u, feedback: true }));
    setFeedbackOpen(true);
  }, []);
  const ctx = useMemo(() => ({ site, map, openRequest, openAllLibrary, trackCta }), [site, map, openRequest, openAllLibrary, trackCta]);
  const figuresNav = map?.groups.find((g) => g.key === "figures")?.items ?? [
    { label: "找图", href: "/" },
    { label: "提需求", href: "/request" },
    { label: "投图", href: "/submit" },
  ];

  return (
    <GalleryContext.Provider value={ctx}>
      <div className="flex min-h-dvh flex-col bg-background">
        <SiteHeader
          brand={map?.brands.figures ?? { name: "心理学科研图库", href: "/" }}
          nav={figuresNav}
          current={location.pathname}
          cta={map ? { text: map.cta.text, href: map.cta.site_url, onClick: () => trackCta("header", "site") } : undefined}
          actions={
            <>
              {map?.unlock_enabled !== false ? (
                <button type="button" onClick={openAllLibrary} className={linkClass}>
                  要全部图库？
                </button>
              ) : null}
              <button type="button" onClick={openFeedback} className={linkClass}>
                意见反馈
              </button>
            </>
          }
        />
        <div className="flex-1">
          <Outlet />
        </div>
        <SiteFooter
          company={map?.company}
          creditCode={map?.credit_code}
          icp={map?.icp}
          icpUrl={map?.icp_url}
          groups={map?.groups ?? []}
          note={`图片版权归原作者和期刊，仅供学习参考。${map?.library_version ? `图库 ${map.library_version} 版。` : ""}`}
        />
      </div>

      <Suspense fallback={null}>
        {used.request ? (
          <RequestDialog
            open={requestCtx !== null}
            onOpenChange={(o) => !o && setRequestCtx(null)}
            query={requestCtx?.query}
            searchId={requestCtx?.searchId}
            onSubmit={sendRequest}
          />
        ) : null}
        {used.feedback ? (
          <SiteFeedbackDialog
            open={feedbackOpen}
            onOpenChange={setFeedbackOpen}
            page={location.pathname + location.search}
            onRequest={sendRequest}
            onSiteFeedback={sendSiteFeedback}
          />
        ) : null}
        {used.all ? (
          <AllLibraryDialog
            open={allOpen}
            onOpenChange={setAllOpen}
            view={unlock}
            error={unlockError}
            onUpload={async (file) => {
              if (!unlock) return;
              setUnlock(await uploadEvidence(unlock.share_code, getVisitor(), file));
            }}
            onResend={async () => {
              if (!unlock) return;
              setUnlock(await resendUnlock(unlock.share_code, getVisitor()));
            }}
            siteUrl={map?.cta.site_url ?? "/"}
            orderUrl={orderHref(map, "unlock_done")}
            onCta={(target) => trackCta("unlock_done", target)}
          />
        ) : null}
      </Suspense>
      <ScrollRestoration />
    </GalleryContext.Provider>
  );
}
