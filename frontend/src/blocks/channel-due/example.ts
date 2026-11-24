import { defineBlockDemo } from "@/lib/blocks";
import type { DueItem } from "@/lib/shop-types";

import { ChannelDue } from "./ChannelDue";

const at = "2026-11-18T06:20:00Z";
const items: DueItem[] = [
  { kind: "verify", level: "high", title: "小红书订单 P202611180031 等你核对", detail: "到平台订单里对上这个订单号再点通过", inbox_id: 12, platform: "xhs", at },
  { kind: "paste", level: "high", title: "闲鱼订单 3881234567890 的发货文案还没贴", detail: "复制发货文案贴到平台，贴好点「贴好了」", inbox_id: 9, platform: "xy", at },
  { kind: "paid_no_code", level: "high", title: "自有网页单 PS261118142233K7QM4X 付了 29.90 元，没发码", detail: "付款人退款作废太多次", order_id: null, at },
  { kind: "completion", level: "mid", title: "小红书订单 P202611160007 录了 49 小时还没点「平台已完成」", detail: "去平台看一眼：买家确认收货了就点「平台已完成」，退款了点「已退款」", inbox_id: 4, at },
  { kind: "price", level: "mid", title: "小红书商品「常规 1 篇」标价 25.00，设置里是 29.9", detail: "去平台把价改成一样（或改设置）", at },
];
const noop = () => undefined;

export default defineBlockDemo({
  block: "channel-due",
  title: "渠道与收款：该看一眼",
  order: 70,
  component: ChannelDue,
  examples: [
    { name: "有五件事", props: { items, onVerify: noop, onOpen: noop } },
    { name: "都处理完了", props: { items: [], onVerify: noop, onOpen: noop } },
  ],
});
