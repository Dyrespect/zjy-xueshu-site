import { defineBlockDemo } from "@/lib/blocks";
import type { RedeemAction, RedeemView } from "@/lib/entry-types";

import { RedeemCard } from "./RedeemCard";

const buy = [
  { label: "网页下单", text: "在下单页选时长和篇数，付完款页面上直接给激活码。", url: "/order" },
  { label: "闲鱼、小红书、抖音", text: "在平台下单后，激活码和兑换网址在订单的发货消息里。", url: "" },
];
const base: Omit<RedeemView, "state" | "actions"> = {
  code: "PSY-K7QM4XWDN", code_tail: "XWDN", sku_name: "", hours: null, progress: "", stage_label: "", buy,
  code_hint: "激活码是 PSY- 开头、后面 9 位的一串（字母和数字，不含 0、O、1、I、L）。", site_url: "https://psyppt.pilipala.zj.cn",
};
const web: RedeemAction = { entry: "entry.webchat", kind: "claim_web", label: "留在网页做", url: null,
  hint: "在这个网页里和助手聊、传资料；记下聊天地址，换手机也能回来。", primary: true };
const wx: RedeemAction = { entry: "entry.wecom", kind: "link", label: "用微信客服继续", url: "https://work.weixin.qq.com/kf/x",
  hint: "打开后先发一句话；助手没提到你的订单，就把激活码发过去。", primary: false };

export default defineBlockDemo({
  block: "redeem-card",
  title: "兑换网页：认领订单",
  order: 64,
  component: RedeemCard,
  examples: [
    { name: "没认领（两个入口）", props: { view: { ...base, state: "unclaimed", sku_name: "常规 · 1 篇", hours: 5, actions: [web, wx] } } },
    { name: "没认领（微信客服没开）", props: { view: { ...base, state: "unclaimed", sku_name: "长 · 2–3 篇", hours: 8, actions: [web] } } },
    { name: "是这个浏览器认领的", props: { view: { ...base, state: "yours", sku_name: "常规 · 1 篇", hours: 5, progress: "还在收资料（还要：讲几分钟、哪天汇报）",
      actions: [{ ...web, kind: "chat", label: "回到聊天", url: "/chat/x", hint: "" }, wx] } } },
    { name: "别人认领了", props: { view: { ...base, state: "taken", actions: [wx] } } },
    { name: "码对不上", props: { view: { ...base, state: "not_found", actions: [] } } },
    { name: "作废", props: { view: { ...base, state: "void", actions: [{ ...web, kind: "chat", label: "问一下助手", url: "/chat", hint: "" }] } } },
    { name: "还没输入码", props: { view: { ...base, code: "", state: "invalid", actions: [] } } },
  ],
});
