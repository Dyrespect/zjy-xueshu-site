import { defineBlockDemo } from "@/lib/blocks";
import type { InvoiceSettingsData } from "@/lib/invoice-types";

import { InvoiceSettingsForm } from "./InvoiceSettingsForm";

const data: InvoiceSettingsData = {
  config: {
    enabled: true, seller_name: "杭州竹涧云科技有限公司", seller_tax_id: "91330110MAKFUNHCXY", taxpayer_type: "小规模纳税人", tax_rate: "",
    item_name: "技术服务费", special_enabled: false, allow_personal: false, allow_remark: true, required_normal: ["title", "tax_id", "email"],
    required_special: ["title", "tax_id", "email", "bank_name", "bank_account", "address", "phone"], eligible_platforms: ["web"],
    apply_window_days: 0, file_types: ["pdf", "ofd", "xml"], file_max_mb: 10,
    customer_notice: "抬头和税号开出后改不了，请对着单位财务给的信息填，提交前再核对一遍。", promise_text: "开好后发到你填的邮箱，这个页面也能下载。",
    notice_issued: "你的发票开好了（单号 {order_no}，{amount} 元）。打开交付页就能下载：{url}",
    notice_rejected: "你的发票申请没开成（单号 {order_no}）：{reason}。改好后在交付页重新申请：{url}",
    notice_voided: "你单号 {order_no} 的发票作废了：{reason}。",
    confirmed_fields: [],
  },
  finance_fields: {
    taxpayer_type: "纳税人类型", tax_rate: "税率", item_name: "开票项目名称", special_enabled: "开不开专票", allow_personal: "收不收个人抬头",
    apply_window_days: "完成后多久内能申请",
  },
  pending_finance: ["taxpayer_type", "tax_rate", "item_name", "special_enabled", "allow_personal", "apply_window_days"],
  platforms: { web: "自有网页", fk: "发卡站", manual: "后台手动开单", xhs: "小红书", xy: "闲鱼", dy: "抖音" },
};

export default defineBlockDemo({
  block: "invoice-settings",
  title: "后台：发票设置",
  order: 93,
  component: InvoiceSettingsForm,
  examples: [{ name: "默认（都待财务确认）", props: { data, onSave: async () => undefined } }],
});
