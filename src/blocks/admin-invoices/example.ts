import { SAMPLE_CONFIG } from "@/blocks/invoice-form/example";
import { defineBlockDemo } from "@/lib/blocks";
import type { AdminInvoiceRow } from "@/lib/invoice-types";

import { AdminInvoices } from "./AdminInvoices";

const row: AdminInvoiceRow = {
  id: 12, order_id: 137, order_no: "00137", step: "pending", stage_label: "待开票", platform: "web", platform_name: "自有网页",
  source: "checkout", source_label: "下单页预填", kind: "normal", kind_label: "电子普通发票", title_kind: "unit", title: "清华大学",
  tax_id: "12100000400000624D", email: "lab@example.edu.cn", bank_name: "", bank_account: "", address: "", phone: "", remark: "",
  amount: "", invoice_no: "", issue_note: "", reason: "", paid: "39.80", refunded: "0.00", max_amount: "39.80", order_stage: "delivered",
  order_completed: true, gate: "open", warnings: [],
  copy_text: "发票类型：电子普通发票\n抬头：清华大学\n纳税人识别号：12100000400000624D\n项目：技术服务费\n收票邮箱：lab@example.edu.cn\n单号：00137",
  created_at: "2026-11-18T03:00:00Z", requested_at: "2026-11-18T05:00:00Z", issued_at: null, closed_at: null, reopened_from: null,
  files: [], notices: [],
};

const ok = async () => "好了";

export default defineBlockDemo({
  block: "admin-invoices",
  title: "后台：发票列表",
  order: 92,
  component: AdminInvoices,
  examples: [
    {
      name: "待开票（一张部分退款的）",
      props: {
        rows: [row, { ...row, id: 13, order_no: "00141", title: "北京师范大学心理学部", refunded: "9.90", max_amount: "29.90", warnings: ["退过 9.90 元，按退后 29.90 元开"] }],
        config: SAMPLE_CONFIG, onIssue: ok, onReject: ok, onVoid: ok, onEdit: ok,
      },
    },
    {
      name: "已开票",
      props: {
        rows: [{ ...row, step: "issued", stage_label: "已开票", amount: "39.80", files: [{ id: 1, name: "发票.pdf", kind: "pdf", size: 86000, url: "#" }] }],
        config: SAMPLE_CONFIG, onIssue: ok, onReject: ok, onVoid: ok, onEdit: ok,
      },
    },
    { name: "空", props: { rows: [], config: SAMPLE_CONFIG, onIssue: ok, onReject: ok, onVoid: ok, onEdit: ok, empty: "没有待开的发票" } },
  ],
});
