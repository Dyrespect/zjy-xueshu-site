import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useParams, useSearchParams } from "react-router";

import { PayInvoice } from "@/blocks/invoice-panel/load";
import { OrderPaid } from "@/blocks/order-paid";
import { PayPanel, type WechatPhase } from "@/blocks/pay-panel";
import { SiteFrame } from "@/blocks/site-shell/load";
import { ApiError } from "@/lib/api";
import { fakePay, getCheckout, repayCheckout, type CheckoutView } from "@/lib/shop";
import { inWechat, isWxPayParams, wechatPay } from "@/lib/wxpay";

/** 服务号网页授权回来出了事（后端 /api/shop/wx/callback 带回的 ?wx=）→ 给客人的一句话 */
const WX_MESSAGES: Record<string, string> = {
  state: "微信授权没对上（可能同时开了两个付款页），点下面再试一次。",
  denied: "没拿到微信授权，点下面再试一次。",
  fail: "微信授权出了点问题，点下面再试一次；还不行就用电脑打开这个网址扫码付。",
  snapshot: "现在是微信的预览页，付不了款：点页面下方「访问完整网页」，再点下面的按钮。",
  notwechat: "这一步要在微信里打开：复制这一页的网址发到微信里，点开就能付。",
  order: "微信那边没下成单，点下面再试一次；还不行就回去重新下单。",
};

/**
 * /order/pay/:token 付款页：每 2.5 秒问一次付了没（后端顺手去网关查单，回调丢了也能补上），付了就出激活码。
 * 微信里（docs/任务单/11_手机微信支付_设计.md）：授权回来落在这一页，自动调起一次微信收银台；微信说 ok 只换提示、加快轮询，
 * 付没付以后端（通知、查单）为准。手机浏览器（微信 H5）：点按钮时才要微信付款链接，付完从微信跳回这一页。
 */
export function PayPage() {
  const { token = "" } = useParams();
  const [params] = useSearchParams();
  const wx = params.get("wx") ?? "";
  const invoiceNote = (useLocation().state as { invoiceNote?: string } | null)?.invoiceNote ?? ""; // 下单页发票信息没存上时的一句
  const [view, setView] = useState<CheckoutView | null>(null);
  const [missing, setMissing] = useState(false);
  const [now, setNow] = useState(() => Date.now());
  const [fakePaying, setFakePaying] = useState(false);
  const [phase, setPhase] = useState<WechatPhase>("idle");
  const [h5Busy, setH5Busy] = useState(false);
  const [h5Error, setH5Error] = useState("");
  const autoPaid = useRef(false);
  const autoOauth = useRef(false);

  const load = useCallback(() => {
    getCheckout(token)
      .then(setView)
      .catch((e) => {
        if (e instanceof ApiError && e.status === 404) setMissing(true);
      });
  }, [token]);

  useEffect(load, [load]);
  useEffect(() => {
    if (view && view.status !== "pending") return;
    const t = window.setInterval(load, phase === "ok" ? 1500 : 2500); // 微信说付好了：问得勤一点
    return () => window.clearInterval(t);
  }, [load, view, phase]);
  useEffect(() => {
    const t = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(t);
  }, []);

  const payload = view?.pay.payload ?? {};
  const payWechat = useCallback(async () => {
    if (!isWxPayParams(payload)) return;
    setPhase("invoking");
    const r = await wechatPay(payload);
    setPhase(r);
    if (r === "ok") load(); // 只是催一次查单；出不出激活码看后端
  }, [payload, load]);

  // 微信说 ok 之后 20 秒还没查到付款：别让客人干等，给一句话和「再付一次」（同一个商户订单号在微信那边只能付一次，不会重复扣）
  useEffect(() => {
    if (phase !== "ok" || view?.status !== "pending") return;
    const t = window.setTimeout(() => setPhase("slow"), 20000);
    return () => window.clearTimeout(t);
  }, [phase, view?.status]);

  // 授权回来、刷新：自动调起一次（只一次；取消了让客人自己再点）
  useEffect(() => {
    if (view?.status === "pending" && view.pay.kind === "jsapi" && !autoPaid.current) {
      autoPaid.current = true;
      void payWechat();
    }
  }, [view, payWechat]);
  // 还没授权、也没出过错（比如授权中途刷新了）：自动再去授权一次；出过错就停下等客人点「再试一次」，不来回跳
  useEffect(() => {
    if (view?.status === "pending" && view.pay.kind === "oauth" && !wx && !autoOauth.current && typeof payload.url === "string") {
      autoOauth.current = true;
      window.location.replace(payload.url);
    }
  }, [view, wx, payload]);

  const openH5 = () => {
    setH5Busy(true);
    setH5Error("");
    repayCheckout(token)
      .then((v) => {
        setView(v);
        if (v.pay.kind === "redirect" && typeof v.pay.payload.url === "string") window.location.href = v.pay.payload.url;
      })
      .catch((e) => setH5Error(e instanceof Error ? e.message : "没打开，过一会儿再点一次"))
      .finally(() => setH5Busy(false));
  };

  const secondsLeft = view?.expires_at ? (new Date(view.expires_at).getTime() - now) / 1000 : 1;
  const paidNoCode = view && view.status === "paid" && !view.code;
  const pageUrl = typeof window !== "undefined" ? `${window.location.origin}/order/pay/${token}` : "";
  const oauthMessage = view?.pay.kind === "oauth" ? (WX_MESSAGES[wx] ?? (wx ? WX_MESSAGES.fail : "")) : "";

  return (
    <SiteFrame gate={false} noindex cta={false} className="text-base">
      {missing ? (
        <p className="mx-auto max-w-xl px-4 py-16 text-sm text-body sm:px-6">没有这个付款单，回去重新下单。</p>
      ) : !view ? (
        <p className="mx-auto max-w-xl px-4 py-16 text-sm text-muted-foreground sm:px-6">加载中……</p>
      ) : view.code ? (
        <>
          <OrderPaid
            code={view.code}
            redeemUrl={view.redeem_url || "/chat"}
            summary={`${view.sku_name}${view.addons.length ? ` + ${view.addons.map((a) => a.name).join("、")}` : ""}`}
            paidFen={view.total_fen}
          />
          <div className="mx-auto max-w-xl px-4 pb-12 sm:px-6">
            {invoiceNote ? <p className="mb-3 text-sm text-foreground">{invoiceNote}</p> : null}
            <PayInvoice token={token} />
          </div>
        </>
      ) : paidNoCode || ["refunding", "refunded", "part_refunded"].includes(view.status) ? (
        <div className="mx-auto flex max-w-xl flex-col gap-2 px-4 py-16 sm:px-6">
          <h1 className="font-display text-3xl leading-tight font-bold tracking-wide text-foreground">{view.status_label}</h1>
          <p className="text-sm leading-relaxed text-body">{view.message || "这笔付款已经退了。"}</p>
        </div>
      ) : (
        <PayPanel
          view={view}
          secondsLeft={secondsLeft}
          orderHref="/order"
          fakePaying={fakePaying}
          wechat={{ phase, onPay: () => void payWechat() }}
          oauth={typeof payload.url === "string" ? { message: oauthMessage, href: payload.url, retry: inWechat() && wx !== "notwechat" } : undefined}
          h5={{ busy: h5Busy, error: h5Error, onOpen: openH5, onCheck: load }}
          copyUrl={wx === "notwechat" || phase === "nobridge" || !inWechat() ? pageUrl : undefined}
          onFakePay={() => {
            setFakePaying(true);
            fakePay(token)
              .then(setView)
              .catch(() => load())
              .finally(() => setFakePaying(false));
          }}
        />
      )}
    </SiteFrame>
  );
}
