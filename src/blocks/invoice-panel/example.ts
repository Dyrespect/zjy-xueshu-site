import { SAMPLE_CONFIG } from "@/blocks/invoice-form/example";
import { defineBlockDemo } from "@/lib/blocks";
import type { InvoicePanelData, InvoiceView } from "@/lib/invoice-types";

import { InvoicePanel } from "./InvoicePanel";

const base: InvoicePanelData = {
  enabled: true, eligible: true, can_apply: true, why_not: "", order_no: "00137", completed: true, apply_note: "",
  current: null, history: [], config: SAMPLE_CONFIG,
};

const inv: InvoiceView = {
  id: 7, step: "pending", stage: "requested", stage_label: "待开票", note: "已提交，等待开票", kind: "normal", kind_label: "电子普通发票",
  title_kind: "unit", title_kind_label: "单位", title: "清华大学", tax_id: "12100000400000624D", email: "lab@example.edu.cn",
  bank_name: "", bank_account: "", address: "", phone: "", remark: "", amount: "", invoice_no: "", reason: "",
  created_at: null, requested_at: null, issued_at: null, closed_at: null, can_withdraw: true, files: [],
};

const ok = async () => "提交了";

export default defineBlockDemo({
  block: "invoice-panel",
  title: "交付页：发票",
  order: 35,
  component: InvoicePanel,
  examples: [
    { name: "还没申请", props: { data: base, onApply: ok, onWithdraw: ok } },
    { name: "订单没完成（先填好）", props: { data: { ...base, completed: false, apply_note: "订单完成（确认收货）后自动提交开票" }, onApply: ok, onWithdraw: ok } },
    { name: "待开票", props: { data: { ...base, can_apply: false, current: inv }, onApply: ok, onWithdraw: ok } },
    {
      name: "开好了",
      props: {
        data: {
          ...base, can_apply: false,
          current: { ...inv, step: "issued", stage: "issued", stage_label: "已开票", note: "发票开好了", amount: "39.80", can_withdraw: false,
            files: [{ id: 1, name: "发票.pdf", kind: "pdf", size: 86_000, url: "#" }, { id: 2, name: "发票.ofd", kind: "ofd", size: 41_000, url: "#" }] },
        },
        onApply: ok, onWithdraw: ok,
      },
    },
    {
      name: "被驳回了",
      props: {
        data: { ...base, history: [{ ...inv, step: "rejected", stage: "rejected", stage_label: "没开成", note: "没开成：税号和抬头对不上", reason: "税号和抬头对不上", can_withdraw: false }] },
        onApply: ok, onWithdraw: ok,
      },
    },
    { name: "平台单", props: { data: { ...base, eligible: false, can_apply: false, why_not: "这单是在小红书下的，发票请在下单的平台申请" }, onApply: ok, onWithdraw: ok } },
  ],
});
