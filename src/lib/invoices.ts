/**
 * 开票的接口：客人（交付页 /api/invoices/order/:令牌、付款页 /api/invoices/checkout/:令牌、下单页预填 /api/invoices/drafts）
 * 和后台（/api/admin/invoices）。只通过 api.ts 发请求。
 */
import { api, apiGet, apiPost, apiUpload } from "./api";
import type {
  AdminInvoiceList,
  AdminInvoiceStatus,
  InvoiceFields,
  InvoiceMetrics,
  InvoiceNoticeRow,
  InvoicePanelData,
  InvoicePublicConfig,
  InvoiceSettingsData,
  InvoiceSubmitResult,
  OrderLookup,
  InvoiceConfigFull,
} from "./invoice-types";

export * from "./invoice-types";

const enc = encodeURIComponent;

// ---------------- 客人 ----------------

export const getInvoiceConfig = () => apiGet<InvoicePublicConfig>("/invoices/config");
export const saveInvoiceDraft = (checkoutToken: string, fields: InvoiceFields) =>
  apiPost<InvoiceSubmitResult>("/invoices/drafts", { checkout_token: checkoutToken, fields, confirmed: true });

export const getDeliveryInvoice = (token: string) => apiGet<InvoicePanelData>(`/invoices/order/${enc(token)}`);
export const applyDeliveryInvoice = (token: string, fields: InvoiceFields) =>
  apiPost<InvoiceSubmitResult>(`/invoices/order/${enc(token)}/apply`, { fields, confirmed: true });
export const withdrawDeliveryInvoice = (token: string, invoiceId: number) =>
  apiPost<InvoiceSubmitResult>(`/invoices/order/${enc(token)}/withdraw`, { invoice_id: invoiceId });

export const getCheckoutInvoice = (token: string) => apiPost<InvoicePanelData>(`/invoices/checkout/${enc(token)}`);
export const applyCheckoutInvoice = (token: string, fields: InvoiceFields) =>
  apiPost<InvoiceSubmitResult>(`/invoices/checkout/${enc(token)}/apply`, { fields, confirmed: true });
export const withdrawCheckoutInvoice = (token: string, invoiceId: number) =>
  apiPost<InvoiceSubmitResult>(`/invoices/checkout/${enc(token)}/withdraw`, { invoice_id: invoiceId });

// ---------------- 后台 ----------------

export const listAdminInvoices = (status: AdminInvoiceStatus) => apiGet<AdminInvoiceList>("/admin/invoices", { status });
export const exportInvoicesUrl = (status: AdminInvoiceStatus) => `/api/admin/invoices/export.csv?status=${enc(status)}`;
export const getInvoiceMetrics = (days = 7) => apiGet<InvoiceMetrics>("/admin/invoices/metrics", { days });
export const getInvoiceSettings = () => apiGet<InvoiceSettingsData>("/admin/invoices/settings");
export const saveInvoiceSettings = (config: InvoiceConfigFull) =>
  api<InvoiceSettingsData>("/admin/invoices/settings", { method: "PUT", json: { config } });

export function issueInvoice(id: number, body: { files: File[]; amount: string; invoice_no: string; note: string }) {
  const form = new FormData();
  for (const f of body.files) form.append("files", f);
  form.append("amount", body.amount);
  form.append("invoice_no", body.invoice_no);
  form.append("note", body.note);
  return apiUpload<{ exit: string; amount: string; detail: string }>(`/admin/invoices/${id}/issue`, form);
}

export const rejectInvoice = (id: number, reason: string) =>
  apiPost<{ exit: string; detail: string }>(`/admin/invoices/${id}/reject`, { reason });
export const voidInvoice = (id: number, reason: string, reopen: boolean, fields?: InvoiceFields) =>
  apiPost<{ exit: string; detail: string; new_invoice_id: number | null; note: string }>(`/admin/invoices/${id}/void`, {
    reason,
    reopen,
    fields: fields ?? null,
  });
export const patchInvoice = (id: number, fields: InvoiceFields) =>
  api<{ ok: boolean }>(`/admin/invoices/${id}`, { method: "PATCH", json: fields });
export const lookupOrderForInvoice = (orderId: number) => apiGet<OrderLookup>("/admin/invoices/order-lookup", { order_id: orderId });
export const manualInvoice = (orderId: number, fields: InvoiceFields) =>
  apiPost<{ exit: string; detail: string; invoice_id: number | null }>("/admin/invoices/manual", { order_id: orderId, fields });
export const listInvoiceNotices = () => apiGet<{ rows: InvoiceNoticeRow[] }>("/admin/invoices/notices");
export const markNoticeSent = (id: number) => apiPost<{ ok: boolean }>(`/admin/invoices/notices/${id}/sent`);
export const runInvoiceSweep = () => apiPost<Record<string, unknown>>("/admin/invoices/sweep");
