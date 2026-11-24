/**
 * 入口模块（D）的接口：兑换网页（/api/channels/redeem/*）、可选的「我的订单」（/api/channels/account/*）、
 * 后台「入口」页（/api/admin/entry/*）。只通过 api.ts 发请求。
 */
import { api, apiGet, apiPost } from "./api";
import { rememberedChatKey } from "./intake";
import type { ClaimWebResult, EntryAdmin, EntryConfig, MyOrders, RedeemView, SentCode } from "./entry-types";

export * from "./entry-types";

// ---------------- 兑换网页

export const getRedeemMeta = () => apiGet<RedeemView>("/channels/redeem");

export function getRedeem(code: string) {
  const key = rememberedChatKey();
  return apiGet<RedeemView>(`/channels/redeem/${encodeURIComponent(code)}`, undefined, {
    headers: key ? { "X-Web-Key": key } : undefined,
  });
}

export const claimOnWeb = (code: string) =>
  apiPost<ClaimWebResult>(`/channels/redeem/${encodeURIComponent(code)}/web`, { key: rememberedChatKey() });

// ---------------- 我的订单（没配邮件服务时整块关闭）

const ACCOUNT_STORE = "xshb.account.token";

export function rememberedAccount(): string | null {
  try {
    return window.localStorage.getItem(ACCOUNT_STORE);
  } catch {
    return null;
  }
}

export function rememberAccount(token: string | null): void {
  try {
    if (token) window.localStorage.setItem(ACCOUNT_STORE, token);
    else window.localStorage.removeItem(ACCOUNT_STORE);
  } catch {
    /* 隐私模式存不了：这一页里还能用，关了要重新登录 */
  }
}

export const getAccountStatus = () => apiGet<{ enabled: boolean }>("/channels/account/status");
export const startBind = (chatKey: string, email: string) =>
  apiPost<SentCode>("/channels/account/bind/start", { chat_key: chatKey, email });
export const verifyBind = (chatKey: string, email: string, code: string, challenge: string) =>
  apiPost<{ ok: boolean; masked: string }>("/channels/account/bind/verify", { chat_key: chatKey, email, code, challenge });
export const startLogin = (orderNo: string, email: string) =>
  apiPost<SentCode>("/channels/account/login/start", { order_no: orderNo, email });
export const verifyLogin = (orderNo: string, email: string, code: string, challenge: string) =>
  apiPost<{ token: string; masked: string }>("/channels/account/login/verify", { order_no: orderNo, email, code, challenge });
export const getMyOrders = (token: string) =>
  apiGet<MyOrders>("/channels/account/orders", undefined, { headers: { "X-Account-Token": token } });

// ---------------- 后台「入口」页

export const getEntryAdmin = () => apiGet<EntryAdmin>("/admin/entry");
export const saveEntryAdmin = (body: { config?: EntryConfig; checklists?: Record<string, unknown> }) =>
  api<EntryAdmin>("/admin/entry", { method: "PUT", json: body });
export const makeWecomLink = (scene = "redeem") => apiPost<EntryAdmin & { url: string }>("/admin/entry/wecom-link", { scene });
