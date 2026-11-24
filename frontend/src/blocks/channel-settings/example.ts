import { overviewExample } from "@/blocks/channel-entry/example";
import { defineBlockDemo } from "@/lib/blocks";
import type { ShopStatus } from "@/lib/shop-types";

import { ChannelSettings } from "./ChannelSettings";

const status: ShopStatus = {
  enabled: true, fake: false, timer: true, timer_minutes: 10, auto_confirm_days: 3, auto_confirm_platforms: ["web", "fk", "manual"],
  checkout_ttl_min: 30, redeem_url: "/chat",
  methods: [
    { method: "wechat_native", label: "微信扫码", node: "pay.wechat", missing: ["WECHATPAY_MCHID", "WECHATPAY_APIV3_KEY"], ready: false, where: "电脑" },
    { method: "wechat_jsapi", label: "微信支付", node: "", missing: [], ready: false, where: "微信里" },
    { method: "wechat_h5", label: "微信支付", node: "", missing: [], ready: false, where: "手机浏览器" },
    { method: "alipay_page", label: "支付宝", node: "pay.alipay", missing: [], ready: true, where: "电脑" },
    { method: "alipay_wap", label: "支付宝", node: "pay.alipay", missing: [], ready: true, where: "手机浏览器" },
  ],
};

export default defineBlockDemo({
  block: "channel-settings",
  title: "渠道与收款：收款设置",
  order: 74,
  component: ChannelSettings,
  examples: [
    {
      name: "微信还缺配置、支付宝能用",
      props: {
        status, overview: overviewExample, settingsHref: "/admin/settings",
        onSaveProfile: async () => undefined, onAddProduct: async () => undefined, onToggleProduct: () => undefined,
        onRunTick: async () => "跑完了：自动确认 0 单，关掉过期单 0 个",
      },
    },
  ],
});
