import { defineBlockDemo } from "@/lib/blocks";
import type { OrderRow } from "@/lib/admin-types";

import { OrderBoard } from "./OrderBoard";

const now = new Date().toISOString();
const row = (o: Partial<OrderRow>): OrderRow => ({
  id: 1, customer_id: 1, name: "", channel: "wecom", platform: "fk", status: "collecting", status_label: "", stage: "collecting",
  progress: "", occasion: "组会文献", duration_min: 15, present_date: null, eta_date: null, start_date: null, due_hours: null,
  quoted_price: "", rush: false, redeemed: true, sku_name: "常规 · 1 篇", tier_name: "常规", maker_state: "", hold_reason: "",
  needs: 0, pending: 0, has_new_deliverable: false, updated_at: now, ...o,
});

export default defineBlockDemo({
  block: "order-board",
  title: "订单看板",
  order: 54,
  component: OrderBoard,
  examples: [
    {
      name: "几单在不同状态",
      props: {
        hrefFor: (r: OrderRow) => (r.customer_id ? `/admin/conversations/${r.customer_id}` : null),
        rows: [
          row({ id: 1, customer_id: null, name: "闲鱼单 XY20261118", channel: "", platform: "xy", stage: "paid", sku_name: "长 · 2–3 篇", occasion: "", duration_min: null, progress: "已付款，等客人来认领" }),
          row({ id: 2, name: "十一", stage: "claimed", sku_name: "轻量 · 1 篇", duration_min: null, progress: "认领了，还没收到资料" }),
          row({ id: 3, name: "青柚", channel: "web", stage: "collecting", duration_min: 20, present_date: "2026-11-25", progress: "资料齐（按清单）：还要：哪天汇报" }),
          row({ id: 4, name: "柳沐", stage: "collecting", present_date: "2026-11-21", progress: "资料齐了，排在 11月19日（周四）开工，开工后 5 小时内交第一版" }),
          row({ id: 5, name: "杭杭吖", stage: "making", occasion: "开题", duration_min: 10, present_date: "2026-11-20", rush: true, sku_name: "常规 · 1 篇 + 加急", progress: "制作方在做" }),
          row({ id: 6, name: "Cici", platform: "xhs", stage: "watermarked", occasion: "会议", duration_min: 12, present_date: "2026-12-14", progress: "交了第 1 版水印版，等客人看", needs: 1 }),
          row({ id: 7, name: "海的湛蓝", stage: "revising", present_date: "2026-11-24", progress: "改第 1 版", hold_reason: "平台申请退款" }),
          row({ id: 8, name: "何小懒", platform: "manual", stage: "delivered", progress: "最终版发了" }),
          row({ id: 9, name: "撤单的", stage: "void" }),
        ],
      },
    },
  ],
});
