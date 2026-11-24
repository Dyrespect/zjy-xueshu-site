import { defineBlockDemo } from "@/lib/blocks";
import type { ChannelOverview } from "@/lib/shop-types";

import { ChannelEntry } from "./ChannelEntry";

export const overviewExample: ChannelOverview = {
  profiles: [
    { platform: "xhs", label: "小红书", adapter: "manual_paste", adapters: ["manual_paste", "fixed_link"], enabled: true, mode: "parse_paid", delivery_template: "code_and_url", allow_url: true, remind_after_paid_hours: 49, confirm: ["platform", "edison"] },
    { platform: "xy", label: "闲鱼", adapter: "manual", adapters: ["manual"], enabled: true, mode: "parse_paid", delivery_template: "code_and_url", allow_url: true, remind_after_paid_hours: 240, confirm: ["edison"] },
    { platform: "dy", label: "抖音", adapter: "openapi", adapters: ["openapi"], enabled: false, mode: "parse_paid", delivery_template: "code_only", allow_url: false, remind_after_paid_hours: 72, confirm: ["platform", "edison"] },
  ],
  products: [
    { id: 2, platform: "xhs", product_ref: "6741a0f2000000001e01", title: "组会汇报 PPT · 常规 1 篇", sku: "regular-p1", addons: [], sku_name: "常规 · 1 篇", listed_price: "29.90", price: "29.9", price_ok: true, token: "q7Kd2mWx0aPc", link: "https://psyppt.pilipala.zj.cn/x/q7Kd2mWx0aPc", active: true, note: "" },
    { id: 1, platform: "xy", product_ref: "闲鱼-常规1篇", title: "常规 1 篇", sku: "regular-p1", addons: [], sku_name: "常规 · 1 篇", listed_price: "25.00", price: "29.9", price_ok: false, token: "Hn3s9QpLr2Vt", link: "https://psyppt.pilipala.zj.cn/x/Hn3s9QpLr2Vt", active: true, note: "" },
  ],
  skus: [
    { sku: "light-p1", name: "轻量 · 1 篇", price: "24.9" },
    { sku: "regular-p1", name: "常规 · 1 篇", price: "29.9" },
    { sku: "regular-p2_3", name: "常规 · 2–3 篇", price: "39.9" },
    { sku: "long-p1", name: "长 · 1 篇", price: "44.9" },
    { sku: "addon-revision", name: "加购：再改一轮", price: "9.9" },
  ],
  addons: [
    { key: "rush", name: "加急", price: "9.9" },
    { key: "revision", name: "再改一轮", price: "9.9" },
    { key: "find_refs", name: "帮我找文献", price: "9.9" },
  ],
};

export default defineBlockDemo({
  block: "channel-entry",
  title: "渠道与收款：人工录单",
  order: 71,
  component: ChannelEntry,
  examples: [
    {
      name: "录一单",
      props: {
        overview: overviewExample,
        onSubmit: async () => ({ exit: "manual", detail: "", inbox_id: 3, order_id: 41, code: "PSY-K7QM4XWDN",
          text: "激活码：PSY-K7QM4XWDN\n打开 https://psyppt.pilipala.zj.cn/c/PSY-K7QM4XWDN 查看并兑换。" }),
        onPasted: () => undefined,
      },
    },
  ],
});
