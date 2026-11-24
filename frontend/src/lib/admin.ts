/**
 * 后台的接口（/api/auth/*、/api/admin/intake/*）。只通过 api.ts 发请求；区块的 load.ts 和后台页面调这里。
 */
import { API_BASE, api, apiGet, apiPost, apiUpload } from "./api";
import type {
  AdminSettings,
  BizConfig,
  CodeGenerateIn,
  CodeList,
  ConversationDetail,
  ConversationRow,
  FactoryJob,
  NodeCatalog,
  OrderDetail,
  OrderPatch,
  OrderRow,
} from "./admin-types";

export * from "./admin-types";

const A = "/admin/intake";

export const adminMe = () => apiGet<{ admin: boolean }>("/auth/me");
export const adminLogin = (password: string) => apiPost<{ admin: boolean }>("/auth/login", { password });
export const adminLogout = () => apiPost<{ admin: boolean }>("/auth/logout");

export const listConversations = () => apiGet<ConversationRow[]>(`${A}/conversations`);
export const getConversation = (id: number) => apiGet<ConversationDetail>(`${A}/conversations/${id}`);
export const approveOutbox = (id: number, text?: string) =>
  apiPost<{ id: number; status: string; error: string }>(`${A}/outbox/${id}/approve`, { text: text ?? null });
export const rejectOutbox = (id: number) => apiPost<{ id: number; status: string }>(`${A}/outbox/${id}/reject`);
export const sendAsEdison = (cid: number, text: string) =>
  apiPost<{ id: number; status: string; error: string }>(`${A}/conversations/${cid}/messages`, { text });
export const setTakeover = (cid: number, on: boolean) =>
  apiPost<{ takeover: boolean; note: string }>(`${A}/conversations/${cid}/takeover`, { on });
export const patchCustomer = (cid: number, body: { nickname?: string; note?: string }) =>
  api<{ ok: boolean }>(`${A}/conversations/${cid}`, { method: "PATCH", json: body });

export const patchOrder = (oid: number, body: OrderPatch) =>
  api<OrderDetail>(`${A}/orders/${oid}`, { method: "PATCH", json: body });
export const setOrderRush = (oid: number, value: boolean) =>
  apiPost<OrderDetail>(`${A}/orders/${oid}/flags`, { flag: "rush", value });
/** 按流程里标了 manual 的连线手动推一步（不合法的 409） */
export const pushOrder = (oid: number, on: string) => apiPost<OrderDetail>(`${A}/orders/${oid}/push`, { on });
/** 作废：return 撤单（码退回还能用）/ void 退款（码作废） */
export const voidOrder = (oid: number, code_action: "return" | "void", why = "") =>
  apiPost<OrderDetail>(`${A}/orders/${oid}/void`, { code_action, why });
export const confirmOrder = (oid: number) => apiPost<OrderDetail>(`${A}/orders/${oid}/confirm`);
export const releaseFinal = (oid: number) => apiPost<OrderDetail>(`${A}/orders/${oid}/release-final`);
export const createManualOrder = (cid: number, sku: string, why = "") =>
  apiPost<OrderDetail>(`${A}/conversations/${cid}/manual-order`, { sku, why });
export const resolveNeed = (oid: number, idx: number) => apiPost<{ ok: boolean }>(`${A}/orders/${oid}/needs/${idx}/resolve`);
export const setFilePurpose = (oid: number, fid: number, purpose: string) =>
  apiPost<OrderDetail>(`${A}/orders/${oid}/files/${fid}/purpose`, { purpose });
export const startNow = (oid: number) => apiPost<OrderDetail>(`${A}/orders/${oid}/start-now`);
export function uploadDeliverable(oid: number, file: File, kind: string) {
  const form = new FormData();
  form.append("file", file);
  form.append("kind", kind);
  return apiUpload<OrderDetail>(`${A}/orders/${oid}/deliverables`, form);
}
export const listFactoryJobs = () => apiGet<FactoryJob[]>(`${A}/factory-jobs`);
export const deliverableFromFactory = (oid: number, job: string, filename: string, kind: string) =>
  apiPost<OrderDetail>(`${A}/orders/${oid}/deliverables/from-factory`, { job, filename, kind });
/** 交这一版（传好的最终版 + 整页图 → 出水印图、发布给客户看） */
export const deliverOrder = (oid: number) => apiPost<OrderDetail>(`${A}/orders/${oid}/deliver`);
/** 不加急的单压着的水印版：现在就发（/api/admin/delivery） */
export const releaseNow = (oid: number) => apiPost<{ order_id: number; published: boolean }>(`/admin/delivery/orders/${oid}/release-now`);
/** 作废这一版还没发布的文件（传错了、要整版重传） */
export const discardUnpublished = (oid: number) => apiPost<OrderDetail>(`${A}/orders/${oid}/discard-unpublished`);

export const listOrders = () => apiGet<OrderRow[]>(`${A}/orders`);
export const getAdminSettings = () => apiGet<AdminSettings>(`${A}/settings`);
export const saveAdminSettings = (config: BizConfig) =>
  api<{ config: BizConfig }>(`${A}/settings`, { method: "PUT", json: { config } });
export const createContactWay = (scene: string) =>
  apiPost<{ url: string; scene: string }>(`${A}/wecom/contact-way`, { scene });

// ---------------- 激活码（/api/admin/intake/codes） ----------------

export const listCodes = (q: { status?: string; sku?: string; batch?: string; q?: string } = {}) =>
  apiGet<CodeList>(`${A}/codes`, q);
export const generateCodes = (body: CodeGenerateIn) =>
  apiPost<{ batch: string; count: number; codes: string[] }>(`${A}/codes/generate`, body);
export const voidCode = (id: number) => apiPost<unknown>(`${A}/codes/${id}/void`);
/** 下载 CSV 的地址（发卡站导入格式，一个货号一个文件）：给 <a href> 用，浏览器带着登录 cookie 去下 */
export function codesExportUrl(q: { batch?: string; sku?: string }): string {
  const params = new URLSearchParams();
  if (q.batch) params.set("batch", q.batch);
  if (q.sku) params.set("sku", q.sku);
  return `${API_BASE}${A}/codes/export.csv?${params.toString()}`;
}

// ---------------- 节点目录 ----------------

export const getNodeCatalog = () => apiGet<NodeCatalog>("/admin/nodes");
