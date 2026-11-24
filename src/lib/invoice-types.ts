/** 开票（/api/invoices/*、/api/admin/invoices/*）的类型。设计：docs/任务单/07_开票_设计.md。 */

export type InvoiceKind = "normal" | "special";
export type TitleKind = "unit" | "personal";
export type FieldKey = "title" | "tax_id" | "email" | "bank_name" | "bank_account" | "address" | "phone" | "remark";

export interface InvoiceFields {
  kind: InvoiceKind;
  title_kind: TitleKind;
  title: string;
  tax_id: string;
  email: string;
  bank_name: string;
  bank_account: string;
  address: string;
  phone: string;
  remark: string;
}

export const EMPTY_FIELDS: InvoiceFields = {
  kind: "normal",
  title_kind: "unit",
  title: "",
  tax_id: "",
  email: "",
  bank_name: "",
  bank_account: "",
  address: "",
  phone: "",
  remark: "",
};

export interface InvoiceKindOption {
  key: InvoiceKind;
  label: string;
  required: FieldKey[];
}

export interface InvoicePublicConfig {
  enabled: boolean;
  kinds: InvoiceKindOption[];
  allow_personal: boolean;
  allow_remark: boolean;
  labels: Record<string, string>;
  notice: string;
  promise: string;
  seller_name: string;
  item_name: string;
}

export interface InvoiceFileLink {
  id: number;
  name: string;
  kind: string;
  size: number;
  url: string;
}

/** 客人页面上的一张申请（step：prefill 预填 / waiting 等订单完成 / pending 待开票 / issued / rejected / blocked / voided / cancelled） */
export interface InvoiceView extends InvoiceFields {
  id: number;
  step: string;
  stage: string;
  stage_label: string;
  note: string;
  kind_label: string;
  title_kind_label: string;
  amount: string;
  invoice_no: string;
  reason: string;
  created_at: string | null;
  requested_at: string | null;
  issued_at: string | null;
  closed_at: string | null;
  can_withdraw: boolean;
  files: InvoiceFileLink[];
}

export interface InvoicePanelData {
  enabled: boolean;
  eligible: boolean;
  can_apply: boolean;
  why_not: string;
  order_no: string;
  completed: boolean;
  apply_note: string;
  current: InvoiceView | null;
  history: InvoiceView[];
  config: InvoicePublicConfig;
}

export interface InvoiceSubmitResult {
  exit: string;
  invoice_id: number | null;
  note: string;
}

// ---------------- 后台 ----------------

export interface AdminInvoiceRow extends InvoiceFields {
  id: number;
  order_id: number | null;
  order_no: string;
  step: string;
  stage_label: string;
  platform: string;
  platform_name: string;
  source: string;
  source_label: string;
  kind_label: string;
  amount: string;
  invoice_no: string;
  issue_note: string;
  reason: string;
  paid: string;
  refunded: string;
  max_amount: string;
  order_stage: string;
  order_completed: boolean;
  gate: string;
  warnings: string[];
  copy_text: string;
  created_at: string;
  requested_at: string | null;
  issued_at: string | null;
  closed_at: string | null;
  reopened_from: number | null;
  files: InvoiceFileLink[];
  notices: { id: number; channel: string; status: string; kind: string }[];
}

export type AdminInvoiceStatus = "pending" | "draft" | "issued" | "closed" | "all";

export interface AdminInvoiceList {
  rows: AdminInvoiceRow[];
  counts: Record<string, number>;
  pending_finance: string[];
}

export interface InvoiceConfigFull {
  enabled: boolean;
  seller_name: string;
  seller_tax_id: string;
  taxpayer_type: "小规模纳税人" | "一般纳税人" | "";
  tax_rate: string;
  item_name: string;
  special_enabled: boolean;
  allow_personal: boolean;
  allow_remark: boolean;
  required_normal: FieldKey[];
  required_special: FieldKey[];
  eligible_platforms: string[];
  apply_window_days: number;
  file_types: string[];
  file_max_mb: number;
  customer_notice: string;
  promise_text: string;
  notice_issued: string;
  notice_rejected: string;
  notice_voided: string;
  confirmed_fields: string[];
}

export interface InvoiceSettingsData {
  config: InvoiceConfigFull;
  finance_fields: Record<string, string>;
  pending_finance: string[];
  platforms: Record<string, string>;
}

export interface InvoiceMetrics {
  days: number;
  completed_orders: number;
  orders_with_request: number;
  request_rate: number | null;
  issued: number;
  issue_hours_avg: number | null;
  issue_hours_median: number | null;
  issue_hours_max: number | null;
  pending_now: number;
  pending_oldest_hours: number | null;
  notices_pending: number;
}

export interface InvoiceNoticeRow {
  id: number;
  invoice_id: number;
  order_no: string;
  channel: string;
  kind: string;
  target: string;
  subject: string;
  text: string;
  created_at: string;
}

export interface OrderLookup {
  order_id: number;
  order_no: string;
  platform: string;
  platform_name: string;
  stage_label: string;
  gate: string;
  reason: string;
  warnings: string[];
  paid: string;
  refunded: string;
  max_amount: string;
  active_invoice_id: number | null;
}

export const FIELD_ORDER: FieldKey[] = ["title", "tax_id", "email", "address", "phone", "bank_name", "bank_account", "remark"];

/** 前端先查一遍（后端还会再查，以后端为准）：缺哪项、税号位数、邮箱样子。返回 {字段: 一句话}。 */
export function quickCheck(f: InvoiceFields, required: FieldKey[], labels: Record<string, string>): Partial<Record<FieldKey, string>> {
  const out: Partial<Record<FieldKey, string>> = {};
  const need = f.title_kind === "personal" ? required.filter((k) => k !== "tax_id") : required;
  for (const k of need) if (!String(f[k] ?? "").trim()) out[k] = `${labels[k] ?? k}没填`;
  const tid = f.tax_id.replace(/[\s-]/g, "").toUpperCase();
  if (tid && !out.tax_id) {
    if (!/^[0-9A-Z]+$/.test(tid)) out.tax_id = "税号只有数字和大写字母";
    else if (![15, 18, 20].includes(tid.length)) out.tax_id = `税号是 15、18 或 20 位，现在是 ${tid.length} 位`;
  }
  const email = f.email.trim();
  if (email && !out.email && !/^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$/.test(email)) out.email = "邮箱格式不对";
  return out;
}

export function yuanText(v: string): string {
  return v ? `${v} 元` : "";
}
