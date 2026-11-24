import { defineBlockDemo } from "@/lib/blocks";

import { MyOrdersList } from "./MyOrders";

export default defineBlockDemo({
  block: "my-orders",
  title: "我的订单（登录后：账号下所有订单）",
  order: 67,
  component: MyOrdersList,
  examples: [
    {
      name: "两单",
      props: {
        masked: "手机 138****5678",
        onLogout: () => undefined,
        onLogoutAll: () => undefined,
        orders: [
          { order_no: "00031", sku_name: "常规 · 1 篇", stage: "watermarked", stage_label: "已交水印版", progress: "第 1 版水印版交了，等你看",
            claimed_at: null, delivery_path: "/d/x", brief_path: null, chat_path: "/chat/k", invoice_hint: "订单完成后能在交付页申请发票" },
          { order_no: "00012", sku_name: "长 · 2–3 篇", stage: "delivered", stage_label: "已交付", progress: "可编辑的 PPT 和讲稿发了",
            claimed_at: null, delivery_path: "/d/y", brief_path: null, chat_path: null, invoice_hint: "发票在交付页里申请和下载" },
        ],
      },
    },
    { name: "没有订单", props: { masked: "微信", orders: [] } },
  ],
});
