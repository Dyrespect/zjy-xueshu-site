/**
 * 微信里调起支付（JSAPI）：只用微信内置浏览器自带的 WeixinJSBridge，不引 JSSDK、不用 wx.config。
 * 写法照官方「JSAPI调起支付」https://pay.weixin.qq.com/doc/v3/merchant/4012791857 ：还没就绪就等 WeixinJSBridgeReady 事件。
 *
 * 结果只回 ok / cancel / fail 给页面。官方原话：「前端回调并不保证它绝对可靠，不可只依赖前端回调判断订单支付状态，
 * 订单状态需以后端查询订单和支付成功回调通知为准」——所以这个文件不发任何请求（scripts/check.py 规矩 22 拦），
 * 页面拿到 ok 也只是换一句提示、接着轮询付款单。
 */

export interface WxPayParams {
  appId: string;
  timeStamp: string;
  nonceStr: string;
  package: string;
  signType: string;
  paySign: string;
}

/** ok 微信说付完了（还要等后端确认）/ cancel 客人取消 / fail 没付成 / nobridge 不在微信里、调不起来 */
export type WxPayResult = "ok" | "cancel" | "fail" | "nobridge";

interface Bridge {
  invoke(name: string, params: Record<string, string>, cb: (res: { err_msg?: string }) => void): void;
}

declare global {
  interface Window {
    WeixinJSBridge?: Bridge;
  }
}

export function inWechat(): boolean {
  return typeof navigator !== "undefined" && /MicroMessenger/i.test(navigator.userAgent);
}

function waitBridge(timeoutMs: number): Promise<Bridge | null> {
  if (window.WeixinJSBridge) return Promise.resolve(window.WeixinJSBridge);
  if (!inWechat()) return Promise.resolve(null);
  return new Promise((resolve) => {
    const done = () => {
      document.removeEventListener("WeixinJSBridgeReady", done);
      window.clearTimeout(timer);
      resolve(window.WeixinJSBridge ?? null);
    };
    const timer = window.setTimeout(done, timeoutMs);
    document.addEventListener("WeixinJSBridgeReady", done, false);
  });
}

export function isWxPayParams(p: Record<string, unknown>): p is Record<string, unknown> & WxPayParams {
  return ["appId", "timeStamp", "nonceStr", "package", "signType", "paySign"].every((k) => typeof p[k] === "string" && p[k]);
}

/** 打开微信收银台。参数原样用后端算好的（appId 和下单的 appid 是同一个，paySign 用商户私钥签过）。 */
export async function wechatPay(p: WxPayParams, timeoutMs = 5000): Promise<WxPayResult> {
  const bridge = await waitBridge(timeoutMs);
  if (!bridge) return "nobridge";
  return new Promise((resolve) => {
    bridge.invoke(
      "getBrandWCPayRequest",
      { appId: p.appId, timeStamp: p.timeStamp, nonceStr: p.nonceStr, package: p.package, signType: p.signType, paySign: p.paySign },
      (res) => {
        const m = res?.err_msg ?? "";
        resolve(m === "get_brand_wcpay_request:ok" ? "ok" : m === "get_brand_wcpay_request:cancel" ? "cancel" : "fail");
      },
    );
  });
}
