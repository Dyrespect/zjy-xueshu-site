import { defineBlockDemo } from "@/lib/blocks";
import type { WebOrderRow } from "@/lib/shop-types";

import { ChannelWebOrders } from "./ChannelWebOrders";

const at = "2026-11-18T06:02:00Z";
const row = (o: Partial<WebOrderRow>): WebOrderRow => ({
  id: 1, out_trade_no: "PS261118140233K7QM4X", status: "paid", status_label: "已付款", sku_name: "常规 · 2–3 篇", addons: ["再改一轮 × 1"],
  amount: "49.80", amount_fen: 4980, paid_fen: 4980, refunded_fen: 0, method: "微信扫码", pay_node: "pay.wechat", order_id: 41,
  code: "PSY-B8HR4XAUA", create_exit: "created", ua_kind: "pc", source: "gzh", created_at: at, paid_at: at, refunds: [], ...o,
});

export default defineBlockDemo({
  block: "channel-web-orders",
  title: "渠道与收款：网页订单和退款",
  order: 73,
  component: ChannelWebOrders,
  examples: [
    {
      name: "已付、部分退款、待付款",
      props: {
        rows: [
          row({ id: 3 }),
          row({ id: 2, sku_name: "常规 · 1 篇", addons: ["加急"], amount: "39.80", amount_fen: 3980, paid_fen: 3980, refunded_fen: 990, status: "part_refunded",
                status_label: "部分退款", order_id: 38, code: "PSY-3HNP8RTAN", method: "支付宝", pay_node: "pay.alipay",
                refunds: [{ id: 1, amount: "9.90", status: "success", status_label: "退款成功", reason: "加急没做到", scope: "addon:rush", void_result: "部分退款，订单不动", created_at: at }] }),
          row({ id: 1, status: "pending", status_label: "待付款", order_id: null, code: "", create_exit: "", paid_fen: 0, paid_at: null }),
        ],
        onRefund: async () => "退款成功",
      },
    },
  ],
});
