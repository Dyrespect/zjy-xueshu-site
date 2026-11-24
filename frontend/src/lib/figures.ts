/**
 * 图库的取数函数（都走 src/lib/api.ts）。区块的 load.ts 和页面用它；区块组件不直接 import 这里。
 */
import { apiGet, apiPost, apiUpload, api } from "@/lib/api";
import type {
  BrowsePage,
  Done,
  FigureCard,
  FigureDetail,
  HomeInfo,
  InboxItem,
  InboxKind,
  InboxList,
  RequestDraft,
  SearchResult,
  SearchStats,
  SiteInfo,
  SubmissionDraft,
} from "@/lib/figures-types";

let sitePromise: Promise<SiteInfo> | null = null;

/** 每页都要的站点信息（页头链接、图型下拉、二维码），一次会话只取一次 */
export function fetchSite(): Promise<SiteInfo> {
  if (!sitePromise) {
    sitePromise = apiGet<SiteInfo>("/figures/site").catch((e) => {
      sitePromise = null;
      throw e;
    });
  }
  return sitePromise;
}

export const fetchHome = () => apiGet<HomeInfo>("/figures/home");

const searchCache = new Map<string, Promise<SearchResult>>();

/**
 * 搜索。同一次打开网站里，同一句话 + 同一个图型只真搜一次：从详情页「返回」不再重搜，
 * 也不会多记一条搜索记录（开发时 React 严格模式会把请求发两遍，也靠这里去重）。
 */
export function fetchSearch(q: string, code?: string | null): Promise<SearchResult> {
  const key = `${q}\u0000${code ?? ""}`;
  let hit = searchCache.get(key);
  if (!hit) {
    hit = apiGet<SearchResult>("/figures/search", { q, code: code || undefined });
    hit.catch(() => searchCache.delete(key));
    searchCache.set(key, hit);
    if (searchCache.size > 30) searchCache.delete(searchCache.keys().next().value as string);
  }
  return hit;
}

export const fetchBrowse = (code: string, offset = 0, limit = 40) =>
  apiGet<BrowsePage>(`/figures/types/${encodeURIComponent(code)}`, { offset, limit });

export const fetchDetail = (id: number) => apiGet<FigureDetail>(`/figures/${id}`);

export const fetchSimilar = (id: number) =>
  apiGet<{ cards: FigureCard[] }>(`/figures/${id}/similar`).then((r) => r.cards);

/** 记一次点击（不等结果，失败也不打扰用户） */
export function logClick(searchId: number | null, figureId: number, position: number, lane: string): void {
  if (searchId == null) return;
  apiPost("/figures/clicks", { search_id: searchId, figure_id: figureId, position, lane }).catch(() => undefined);
}

export const sendFeedback = (
  id: number,
  body: {
    reason: string;
    note: string;
    query: string;
    search_id: number | null;
    website: string;
    proposed?: { what: string };
    credit?: string;
  },
) => apiPost<Done>(`/figures/${id}/feedback`, body);

export function sendRequest(d: RequestDraft): Promise<Done> {
  const f = new FormData();
  f.set("want", d.want);
  f.set("method", d.method);
  f.set("contact", d.contact);
  f.set("query", d.query);
  if (d.searchId != null) f.set("search_id", String(d.searchId));
  f.set("website", d.website);
  if (d.sketch) f.set("sketch", d.sketch);
  return apiUpload<Done>("/figures/requests", f);
}

export function sendSubmission(d: SubmissionDraft): Promise<Done> {
  const f = new FormData();
  f.set("source", d.source);
  f.set("reason", d.reason);
  f.set("credit", d.credit);
  f.set("website", d.website);
  if (d.image) f.set("image", d.image);
  return apiUpload<Done>("/figures/submissions", f);
}

export const sendSiteFeedback = (body: { content: string; contact: string; page: string; website: string }) =>
  apiPost<Done>("/figures/site-feedback", body);

/* ---- 后台 ---- */
export const fetchMe = () => apiGet<{ admin: boolean }>("/auth/me");
export const adminLogin = (password: string) => apiPost<{ admin: boolean }>("/auth/login", { password });
export const adminLogout = () => apiPost<{ admin: boolean }>("/auth/logout");

export const fetchInbox = (kind: InboxKind, status: "all" | "new" | "done" = "all") =>
  apiGet<InboxList>(`/admin/figures/inbox/${kind}`, { status });

export const updateInbox = (kind: InboxKind, id: number, body: { status?: "new" | "done"; admin_note?: string }) =>
  api<InboxItem>(`/admin/figures/inbox/${kind}/${id}`, { method: "PATCH", json: body });

export const fetchStats = () => apiGet<SearchStats>("/admin/figures/stats");
