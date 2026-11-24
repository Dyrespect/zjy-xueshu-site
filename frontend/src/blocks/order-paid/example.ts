import { defineBlockDemo } from "@/lib/blocks";

import { OrderPaid } from "./OrderPaid";

export default defineBlockDemo({
  block: "order-paid",
  title: "付完了：激活码和下一步",
  order: 63,
  component: OrderPaid,
  examples: [
    { name: "自有网页付完", props: { code: "PSY-B8HR4XAUA", redeemUrl: "/chat", summary: "常规 · 2–3 篇 + 再改一轮 × 1", paidFen: 4980 } },
    { name: "平台固定链接核对通过", props: { code: "PSY-K7QM4XWDN", redeemUrl: "/chat", title: "订单号核对好了" } },
  ],
});
