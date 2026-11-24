/**
 * 统一站点地图和聚人这条线的取数（都走 src/lib/api.ts）。区块的 load.ts 和页面用它。
 */
import { api, apiGet, apiPost, apiUpload } from "@/lib/api";
import type {
  AdminPack,
  AdminTakedown,
  AdminUnlock,
  CtaPlacement,
  CtaTarget,
  GatherConfig,
  GatherOverview,
  PackDraft,
  SiteMap,
  TakedownDraft,
  UnlockView,
} from "@/lib/site-types";
import type { Done } from "@/lib/figures-types";

const siteCache = new Map<string, Promise<SiteMap>>();

/** 页头页脚、导流入口、插件名字（一次会话只取一次）。section：现在在哪一块（figures 图库 / app 下单页）。 */
export function fetchSiteMap(section: "figures" | "app" = "figures"): Promise<SiteMap> {
  let hit = siteCache.get(section);
  if (!hit) {
    hit = apiGet<SiteMap>("/gather/site", { section });
    hit.catch(() => siteCache.delete(section));
    siteCache.set(section, hit);
  }
  return hit;
}

/** 记一次来访（不等结果，失败也不打扰）。 */
export function sendVisit(body: { visitor: string; landing: string; src: string; share: string }): void {
  apiPost("/gather/visit", { ...body, referrer_host: "" }).catch(() => undefined);
}

/** 点了「做汇报 PPT」这类入口（keepalive：整页跳走也能发出去）。 */
export function sendCta(placement: CtaPlacement, target: CtaTarget, visitor: string): void {
  apiPost("/gather/cta", { placement, target, visitor }, { keepalive: true }).catch(() => undefined);
}

export const startUnlock = (visitor: string, src: string) => apiPost<UnlockView>("/gather/unlock", { visitor, src });
export const getUnlock = (code: string, visitor: string) =>
  apiGet<UnlockView>(`/gather/unlock/${encodeURIComponent(code)}`, { visitor });
export function uploadEvidence(code: string, visitor: string, image: File): Promise<UnlockView> {
  const f = new FormData();
  f.set("visitor", visitor);
  f.set("image", image);
  return apiUpload<UnlockView>(`/gather/unlock/${encodeURIComponent(code)}/evidence`, f);
}
export const resendUnlock = (code: string, visitor: string) =>
  apiPost<UnlockView>(`/gather/unlock/${encodeURIComponent(code)}/resend`, { visitor });

export const sendTakedown = (d: TakedownDraft) => apiPost<Done>("/figures/takedown", d);

/* ---- 后台 ---- */
export const fetchGatherOverview = (days = 7) => apiGet<GatherOverview>("/admin/gather/overview", { days });
export const fetchAdminUnlocks = (stage = "") =>
  apiGet<{ counts: Record<string, number>; items: AdminUnlock[] }>("/admin/gather/unlocks", { stage: stage || undefined });
export const markEvidence = (id: number, mark: "ok" | "fake" | "") =>
  apiPost<AdminUnlock>(`/admin/gather/evidence/${id}/mark`, { mark });
export const pushUnlock = (id: number, on: string) => apiPost<AdminUnlock>(`/admin/gather/unlocks/${id}/push`, { on });
export const fetchPacks = () => apiGet<{ items: AdminPack[]; waiting: number }>("/admin/gather/packs");
export const releasePack = (d: PackDraft) => apiPost<AdminPack & { resent: number }>("/admin/gather/packs", d);
export const deactivatePack = (id: number) => apiPost<AdminPack>(`/admin/gather/packs/${id}/deactivate`);
export const fetchGatherConfig = () => apiGet<GatherConfig>("/admin/gather/config");
export const saveGatherConfig = (values: Record<string, unknown>) =>
  api<GatherConfig>("/admin/gather/config", { method: "PUT", json: values });
export const fetchGzhReply = () => apiGet<{ keyword: string; text: string; missing: string }>("/admin/gather/gzh-reply");
export const fetchTakedowns = () => apiGet<{ items: AdminTakedown[]; open: number; overdue: number }>("/admin/figures/takedowns");
export const curate = (kind: "tag_fix" | "submit" | "takedown", id: number, decision: "approve" | "reject" | "hide",
  edited: Record<string, unknown> = {}, note = "") =>
  apiPost<{ status: string }>(`/admin/figures/curate/${kind}/${id}`, { decision, edited, note });
