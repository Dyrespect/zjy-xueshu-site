import { defineBlockDemo } from "@/lib/blocks";
import type { InboxRow } from "@/lib/shop-types";

import { ChannelOrders } from "./ChannelOrders";

const at = "2026-11-18T05:12:00Z";
const row = (o: Partial<InboxRow>): InboxRow => ({
  id: 1, platform: "xhs", platform_label: "小红书", source: "manual", platform_order_id: "P202611180031", sku_name: "常规 · 1 篇",
  paid_amount: "29.90", buyer_hint: "", exit: "manual", exit_label: "待贴发货文案", verify_status: "", order_id: 41, code: "PSY-K7QM4XWDN",
  text: "激活码：PSY-K7QM4XWDN\n打开 https://psyppt.pilipala.zj.cn/c/PSY-K7QM4XWDN 查看并兑换。", pasted_at: null, completed_at: null,
  signals: [], error: "", created_at: at, stage: "paid", stage_label: "已付款", hold: false, ...o,
});

export default defineBlockDemo({
  block: "channel-orders",
  title: "渠道与收款：平台订单",
  order: 72,
  component: ChannelOrders,
  examples: [
    {
      name: "三单",
      props: {
        rows: [
          row({ id: 3 }),
          row({ id: 2, platform: "xy", platform_label: "闲鱼", platform_order_id: "3881234567890", code: "PSY-3HNP8RTAN", pasted_at: at, stage: "collecting", stage_label: "收资料" }),
          row({ id: 1, platform_order_id: "P202611150002", code: "PSY-W9EBC2YJN", pasted_at: at, stage: "delivered", stage_label: "已交付", completed_at: at }),
        ],
        onSignal: () => undefined,
        onPasted: () => undefined,
      },
    },
  ],
});
