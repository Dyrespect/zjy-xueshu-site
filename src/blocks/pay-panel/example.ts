import { defineBlockDemo } from "@/lib/blocks";
import type { CheckoutView } from "@/lib/shop-types";

import { PayPanel } from "./PayPanel";

// 一个真的二维码矩阵（weixin://wxpay/bizpayurl?pr=AbCdEf123，后端 paycore/qr.py 画的，29×29）
const QR = [
  "11111110100010100001101111111", "10000010110001100000001000001", "10111010001001111001101011101",
  "10111010110110011100101011101", "10111010000111110001001011101", "10000010010110100011101000001",
  "11111110101010101010101111111", "00000000110101100100100000000", "10110111000001100100101001011",
  "01001100000000000101111110101", "11000110011000100010000100110", "10110100011101110011011000011",
  "01010110110110010100000100111", "01111000100101011111011000001", "00101011011000100001000000011",
  "00011101001011011010000001000", "01100110011000000010000010010", "00111100100111000010100100100",
  "10010011010000010110001100100", "00001100011110001101111000111", "01001011000011001100111110111",
  "00000000100001101101100010101", "11111110110111001111101010010", "10000010111000011010100011011",
  "10111010011100110000111110100", "10111010110111101101110011001", "10111010101010001001100100101",
  "10000010011011100000110100010", "11111110111001100011101010010",
];

const view: CheckoutView = {
  view_token: "demo", status: "pending", status_label: "待付款", total_fen: 4980, expires_at: null, paid_at: null,
  pay: { kind: "qr", payload: { code_url: "weixin://wxpay/bizpayurl?pr=AbCdEf123", qr: QR }, method: "wechat_native", method_label: "微信扫码", simulated: false },
  code: "", redeem_url: "", sku_name: "常规 · 2–3 篇", addons: [{ key: "revision", name: "再改一轮 × 1", price: "9.9" }], hours: 5, message: "",
};

const noop = () => undefined;
// 微信里调起支付的参数（假的；真的由后端用商户私钥签）
const jsapiView: CheckoutView = {
  ...view,
  pay: {
    kind: "jsapi", method: "wechat_jsapi", method_label: "微信支付", simulated: false,
    payload: { appId: "wxdemo", timeStamp: "1763520000", nonceStr: "demo", package: "prepay_id=wxdemo", signType: "RSA", paySign: "demo" },
  },
};

export default defineBlockDemo({
  block: "pay-panel",
  title: "付款（扫码 / 跳支付宝 / 微信里直接付 / 手机浏览器跳微信 / 过期）",
  order: 62,
  component: PayPanel,
  examples: [
    { name: "电脑上微信扫码", props: { view, secondsLeft: 1771, orderHref: "/order" } },
    {
      name: "支付宝（跳过去付）",
      props: {
        view: { ...view, pay: { kind: "redirect", payload: { url: "https://openapi.alipay.com/gateway.do?demo" }, method: "alipay_page", method_label: "支付宝", simulated: false } },
        secondsLeft: 1500, orderHref: "/order",
      },
    },
    { name: "本机假网关", props: { view: { ...view, pay: { ...view.pay, simulated: true } }, secondsLeft: 1700, orderHref: "/order", onFakePay: () => undefined } },
    { name: "过期了", props: { view: { ...view, status: "closed", message: "这个付款单过期关掉了，回去重新下单就好（没付钱不会扣）。" }, secondsLeft: 0, orderHref: "/order" } },
    { name: "微信里：等客人点微信支付", props: { view: jsapiView, secondsLeft: 1700, orderHref: "/order", wechat: { phase: "idle", onPay: noop } } },
    { name: "微信里：取消了", props: { view: jsapiView, secondsLeft: 1650, orderHref: "/order", wechat: { phase: "cancel", onPay: noop } } },
    { name: "微信里：微信说付好了，等确认", props: { view: jsapiView, secondsLeft: 1600, orderHref: "/order", wechat: { phase: "ok", onPay: noop } } },
    {
      name: "微信授权没对上",
      props: {
        view: { ...view, pay: { kind: "oauth", payload: { url: "/api/shop/wx/oauth?t=demo" }, method: "wechat_jsapi", method_label: "微信支付", simulated: false } },
        secondsLeft: 1700, orderHref: "/order",
        oauth: { message: "微信授权没对上（可能同时开了两个付款页），点下面再试一次。", href: "/api/shop/wx/oauth?t=demo" },
      },
    },
    {
      name: "手机浏览器：打开微信付款（H5）",
      props: {
        view: { ...view, pay: { kind: "h5", payload: {}, method: "wechat_h5", method_label: "微信支付", simulated: false } },
        secondsLeft: 1700, orderHref: "/order", h5: { busy: false, error: "", onOpen: noop, onCheck: noop },
      },
    },
  ],
});
