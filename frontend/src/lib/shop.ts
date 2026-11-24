/**
 * 自有网页下单（/api/shop/*）、平台固定链接（/api/platforms/*）、后台「渠道与收款」（/api/admin/shop、/api/admin/platforms）。
 * 只通过 api.ts 发请求。价格一律以后端为准，这里不算钱。
 */
import { api, apiGet, apiPost } from "./api";
import type {
  ChannelOverview,
  ChannelProduct,
  CheckoutView,
  ClaimProduct,
  ClaimView,
  DueItem,
  InboxRow,
  ManualEntryBody,
  ManualEntryResult,
  OrderSelection,
  ShopCatalog,
  ShopQuote,
  ShopStatus,
  SignalKind,
  WebOrderRow,
} from "./shop-types";

export * from "./shop-types";

// ---------------- 客人：下单、付款 ----------------

export const getShopCatalog = () => apiGet<ShopCatalog>("/shop/catalog");
export const getShopQuote = (sel: OrderSelection) => apiPost<ShopQuote>("/shop/quote", sel);
/** 下单：三项勾选和协议版本随单带上（后端没勾全不建单，422），留痕和建单同一个事务 */
export interface CheckoutExtra {
  session_ref?: string;
  source?: string;
  consents?: string[];
  terms_version?: string;
  privacy_version?: string;
}
export const createCheckout = (sel: OrderSelection, method: string, extra: CheckoutExtra = {}) =>
  apiPost<CheckoutView>("/shop/checkout", { ...sel, method, ...extra });
export const getCheckout = (token: string) => apiGet<CheckoutView>(`/shop/checkout/${encodeURIComponent(token)}`);
/** 手机浏览器（微信 H5）：点「打开微信付款」时要一个新鲜的微信付款链接（5 分钟有效）；付没付照旧只看轮询 */
export const repayCheckout = (token: string) => apiPost<CheckoutView>(`/shop/checkout/${encodeURIComponent(token)}/repay`, {});
/** 本机走查用：模拟扫码付了（后端没开假网关时 404） */
export const fakePay = (token: string) => apiPost<CheckoutView>(`/shop/fake/pay/${encodeURIComponent(token)}`, {});

// ---------------- 客人：平台商品的固定链接 ----------------

export const getClaimProduct = (token: string) => apiGet<ClaimProduct>(`/platforms/claim/${encodeURIComponent(token)}`);
export const submitClaim = (product_token: string, platform_order_id: string) =>
  apiPost<ClaimView>("/platforms/claim", { product_token, platform_order_id });
export const getClaimStatus = (claimToken: string) => apiGet<ClaimView>(`/platforms/claim/status/${encodeURIComponent(claimToken)}`);

const CLAIM_STORE = "xshb.claim.";

export function rememberedClaim(productToken: string): string | null {
  try {
    return window.localStorage.getItem(CLAIM_STORE + productToken);
  } catch {
    return null;
  }
}

export function rememberClaim(productToken: string, claimToken: string): void {
  try {
    window.localStorage.setItem(CLAIM_STORE + productToken, claimToken);
  } catch {
    /* 存不了就只在这一页里有效 */
  }
}

// ---------------- 后台 ----------------

export const getShopStatus = () => apiGet<ShopStatus>("/admin/shop/status");
export const listWebOrders = (status = "") => apiGet<{ rows: WebOrderRow[] }>("/admin/shop/checkouts", { status: status || undefined });
export const refundWebOrder = (body: { order_id: number; amount_fen: number; scope: string; reason: string }) =>
  apiPost<{ exit: string; message: string; detail: string }>("/admin/shop/refunds", body);
export const runShopTick = () => apiPost<Record<string, unknown>>("/admin/shop/tick", {});

export const getChannelDue = () => apiGet<{ items: DueItem[] }>("/admin/platforms/due");
export const getChannelOverview = () => apiGet<ChannelOverview>("/admin/platforms/overview");
export const saveChannelProfile = (platform: string, adapter: string, enabled: boolean) =>
  api<Record<string, unknown>>(`/admin/platforms/profiles/${platform}`, { method: "PUT", json: { adapter, enabled } });
export const addChannelProduct = (body: Omit<ChannelProduct, "id" | "sku_name" | "price" | "price_ok" | "token" | "link" | "active">) =>
  apiPost<ChannelProduct>("/admin/platforms/products", body);
export const patchChannelProduct = (id: number, body: Partial<Pick<ChannelProduct, "active" | "listed_price" | "title" | "note">>) =>
  api<ChannelProduct>(`/admin/platforms/products/${id}`, { method: "PATCH", json: body });
export const manualEntry = (body: ManualEntryBody) => apiPost<ManualEntryResult>("/admin/platforms/manual-entry", body);
export const verifyClaim = (inbox_id: number, ok: boolean, buyer_hint = "") =>
  apiPost<{ exit: string; detail: string; code: string }>("/admin/platforms/verify", { inbox_id, ok, buyer_hint });
export const sendSignal = (platform: string, platform_order_id: string, kind: SignalKind) =>
  apiPost<{ exit: string; result: string; stage: string }>(`/admin/platforms/${platform}/signal`, { platform_order_id, kind });
export const markPasted = (inboxId: number) => apiPost<{ ok: boolean }>(`/admin/platforms/inbox/${inboxId}/pasted`);
export const listInbox = (platform = "") => apiGet<{ rows: InboxRow[] }>("/admin/platforms/inbox", { platform: platform || undefined });
