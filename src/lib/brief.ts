/**
 * 需求卡（09 需求引导）的接口：客人页面 /api/channels/brief/*、后台 /api/admin/brief/*。只通过 api.ts 发请求。
 */
import { api, apiGet, apiPost, apiUpload } from "./api";
import type { BriefAdminView, BriefAnswers, BriefSettings, BriefView } from "./brief-types";
import { rememberedChatKey } from "./intake";

export * from "./brief-types";

function keyHeader(): HeadersInit | undefined {
  const k = rememberedChatKey();
  return k ? { "X-Web-Key": k } : undefined;
}

const base = (token: string) => `/channels/brief/${encodeURIComponent(token)}`;

// ---------------- 客人

export const getBrief = (token: string) => apiGet<BriefView>(base(token), undefined, { headers: keyHeader() });

export const saveBrief = (token: string, answers: BriefAnswers) =>
  api<BriefView>(base(token), { method: "PUT", json: { answers }, headers: keyHeader() });

/** 「对，开工」。平台单第一次确认要带三项同意和协议版本（后端没勾全 422） */
export interface BriefConsent {
  consents: string[];
  terms_version: string;
  privacy_version: string;
}
export const confirmBrief = (token: string, version: number, consent?: BriefConsent) =>
  apiPost<BriefView>(`${base(token)}/confirm`, { version, ...(consent ?? {}) }, { headers: keyHeader() });

export function uploadBriefFile(token: string, file: File, kind: "ref" | "template") {
  const form = new FormData();
  form.append("kind", kind);
  form.append("file", file);
  return apiUpload<BriefView>(`${base(token)}/files`, form, { headers: keyHeader() });
}

export const removeBriefFile = (token: string, fileId: number) =>
  api<BriefView>(`${base(token)}/files/${fileId}`, { method: "DELETE", headers: keyHeader() });

// ---------------- 后台

export const getBriefSettings = () => apiGet<{ settings: BriefSettings }>("/admin/brief/settings");
export const saveBriefSettings = (settings: BriefSettings) =>
  api<{ settings: BriefSettings }>("/admin/brief/settings", { method: "PUT", json: { settings } });
export const getOrderBrief = (orderId: number) => apiGet<BriefAdminView>(`/admin/brief/orders/${orderId}`);
export const editOrderBrief = (orderId: number, answers: BriefAnswers, note: string) =>
  api<BriefAdminView>(`/admin/brief/orders/${orderId}`, { method: "PUT", json: { answers, send_back: true, note } });
export const proxyConfirmBrief = (orderId: number, note: string) =>
  apiPost<BriefAdminView>(`/admin/brief/orders/${orderId}/confirm`, { note });
