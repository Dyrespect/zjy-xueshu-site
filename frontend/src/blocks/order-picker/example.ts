import { defineBlockDemo } from "@/lib/blocks";
import type { ShopCatalog, ShopQuote } from "@/lib/shop-types";

import { OrderPicker, type OrderPickerProps } from "./OrderPicker";

// 示例数据照订单中枢设置的默认值（真页面上全从 /api/shop/catalog、/api/shop/quote 来）
export const catalogExample: ShopCatalog = {
  enabled: true,
  tiers: [
    { key: "light", name: "轻量", min_minutes: 1, max_minutes: 15, max_pages: 20, std_hours: 4, rush_hours: 2, rush: true, prices: { p1: "24.9", p2_3: "34.9", p4_5: null } },
    { key: "regular", name: "常规", min_minutes: 16, max_minutes: 25, max_pages: 30, std_hours: 5, rush_hours: 3, rush: true, prices: { p1: "29.9", p2_3: "39.9", p4_5: "49.9" } },
    { key: "long", name: "长", min_minutes: 26, max_minutes: 40, max_pages: 45, std_hours: 8, rush_hours: null, rush: false, prices: { p1: "44.9", p2_3: "54.9", p4_5: "64.9" } },
    { key: "xlong", name: "超长", min_minutes: 41, max_minutes: 60, max_pages: 60, std_hours: 12, rush_hours: null, rush: false, prices: { p1: "59.9", p2_3: "69.9", p4_5: "79.9" } },
  ],
  bands: [
    { key: "p1", name: "1 篇", max_papers: 1 },
    { key: "p2_3", name: "2–3 篇", max_papers: 3 },
    { key: "p4_5", name: "4–5 篇", max_papers: 5 },
  ],
  addons: [
    { key: "rush", name: "加急", price: "9.9", note: "只对轻量、常规、材料齐的单，限名额；做不到退加急费" },
    { key: "revision", name: "再改一轮", price: "9.9", note: "基础价含一轮，可以买多次" },
    { key: "find_refs", name: "帮我找文献", price: "9.9", note: "按 1 篇的价算，找到几篇都含在里面；不开放加急" },
  ],
  find_refs_extra_hours: 2,
  revisions_included: 1,
  auto_confirm_days: 3,
  page_rule_text: "页数按内容页算，不含封面、目录、过渡页、参考文献、致谢",
  methods: [
    { method: "wechat_native", label: "微信扫码" },
    { method: "alipay_page", label: "支付宝" },
  ],
  ua_kind: "pc",
  hint: "",
  notices: [
    "这是按你的材料单独做的定制服务：开工前想撤单可以退款，开始制作后不支持仅退款；基础价含 1 轮修改。",
    "先交水印版：水印版交出后 3 天内没提修改、也没确认，系统自动确认收货，再发可编辑的 PPT 和讲稿。",
    "付款后马上拿到激活码：用它认领订单，再交材料。",
  ],
  site_url: "https://psyppt.pilipala.zj.cn",
  price_hash: "7b4ad482f9c56005",
};

export const quoteExample: ShopQuote = {
  ok: true, why: "", sku: "regular-p2_3", sku_name: "常规 · 2–3 篇", base_price: "39.9",
  addons: [{ key: "revision", name: "再改一轮 × 1", price: "9.9" }], total: "49.8", total_fen: 4980, hours: 5, max_pages: 30,
  rush_ok: true, rush_why: "", earliest_start: "2026-11-19", eta_date: "2026-11-19", queue_full: false, notes: [],
};

const noop = () => undefined;
const base: OrderPickerProps = {
  catalog: catalogExample,
  selection: { tier: "regular", band: "p2_3", rush: false, find_refs: false, extra_revisions: 1 },
  onChange: noop,
  quote: quoteExample,
  method: "wechat_native",
  onMethod: noop,
  onPay: noop,
};

export default defineBlockDemo({
  block: "order-picker",
  title: "下单（选档、篇数、加购、出价）",
  order: 61,
  component: OrderPicker,
  examples: [
    { name: "常规 · 2–3 篇 + 再改一轮", props: base },
    {
      name: "微信里打开（还不能直接付）",
      props: { ...base, catalog: { ...catalogExample, methods: [], ua_kind: "wechat", hint: "在微信里还不能直接付款：点右上角，在浏览器里打开用支付宝付；或者用电脑打开这个网址扫码付。" }, method: "" },
    },
    {
      name: "自有网页暂不收款：去小红书、闲鱼下单（填了小红书链接、闲鱼没填）",
      props: {
        ...base,
        catalog: { ...catalogExample, methods: [], pay_mode: "platforms", hint: "现在请在小红书或闲鱼下单，付款后会收到兑换码" },
        method: "",
        platform: {
          hint: "现在请在小红书或闲鱼下单，付款后会收到兑换码",
          shops: [
            { label: "小红书", url: "https://www.xiaohongshu.com/" },
            { label: "闲鱼", url: "" },
          ],
          note: "两个平台都搜「心理学汇报 PPT 定制」",
        },
      },
    },
    {
      name: "手机浏览器：复制网址到微信里付（微信 H5 没开）",
      props: {
        ...base,
        catalog: { ...catalogExample, methods: [], ua_kind: "mobile", open_in_wechat: true, hint: "手机浏览器里还不能直接付：复制这个网址，到微信里打开就能付（发给自己或文件传输助手，点开就行）。" },
        method: "",
        phone: {
          hint: "手机浏览器里还不能直接付：复制这个网址，到微信里打开就能付（发给自己或文件传输助手，点开就行）。",
          copyUrl: "https://psyppt.pilipala.zj.cn/order?tier=regular&band=p2_3",
          xianyuUrl: "https://www.goofish.com/",
        },
      },
    },
    {
      name: "微信里：直接用微信支付",
      props: { ...base, catalog: { ...catalogExample, methods: [{ method: "wechat_jsapi", label: "微信支付" }], ua_kind: "wechat" }, method: "wechat_jsapi" },
    },
    {
      name: "名额排满",
      props: { ...base, quote: { ...quoteExample, queue_full: true, earliest_start: null, eta_date: null } },
    },
  ],
});
