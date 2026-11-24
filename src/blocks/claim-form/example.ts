import { defineBlockDemo } from "@/lib/blocks";
import type { ClaimProduct } from "@/lib/shop-types";

import { ClaimForm } from "./ClaimForm";

const product: ClaimProduct = { ok: true, platform: "xhs", platform_label: "小红书", title: "组会汇报 PPT · 常规 1 篇", sku_name: "常规 · 1 篇", why: "" };
const noop = () => undefined;

export default defineBlockDemo({
  block: "claim-form",
  title: "平台固定链接：填订单号领激活码",
  order: 64,
  component: ClaimForm,
  examples: [
    { name: "填订单号", props: { product, state: null, onSubmit: noop } },
    { name: "等核对", props: { product, state: { status: "pending", claim_token: "t", code: "", redeem_url: "", message: "收到了，正在核对订单号（一般几分钟），这个页面会自己刷出激活码，别关" }, onSubmit: noop } },
    { name: "没核对上", props: { product, state: { status: "rejected", claim_token: "t", code: "", redeem_url: "", message: "订单号没核对上：回去看一下订单号有没有填错，再提交一次" }, onSubmit: noop } },
    { name: "链接用不了", props: { product: { ...product, ok: false, why: "这个链接现在用不了" }, state: null, onSubmit: noop } },
  ],
});
