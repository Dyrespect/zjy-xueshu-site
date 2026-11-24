import { Check, Copy, ExternalLink, Loader2, RefreshCw } from "lucide-react";
import { type ReactNode, useState } from "react";

import { Button } from "@/components/ui/button";
import { copyText } from "@/lib/clipboard";
import type { CheckoutView } from "@/lib/shop-types";

import { QrCode } from "./QrCode";

/** 微信里调起支付这一下的状态（页面管，面板只显示） */
export type WechatPhase = "idle" | "invoking" | "ok" | "slow" | "cancel" | "fail" | "nobridge";

export interface PayPanelProps {
  view: CheckoutView;
  /** 还剩几秒过期（页面每秒算一次） */
  secondsLeft: number;
  /** 本机走查的「模拟付款」（后端开了假网关才出现） */
  onFakePay?: () => void;
  fakePaying?: boolean;
  /** 重新下单（回下单页） */
  orderHref: string;
  /** 微信里（kind = jsapi）：调起状态 + 再点一次 */
  wechat?: { phase: WechatPhase; onPay: () => void };
  /** 微信里还没授权完（kind = oauth）：出了什么事（空 = 正在跳转）+ 重新授权的地址；retry = false 时不出「再试一次」（不在微信里，点了也没用） */
  oauth?: { message: string; href: string; retry?: boolean };
  /** 手机浏览器（微信 H5）：打开微信付款、付完回来查一下 */
  h5?: { busy: boolean; error: string; onOpen: () => void; onCheck: () => void };
  /** 「不在微信里」时给客人复制的网址（就是这一页） */
  copyUrl?: string;
}

export function yuan(fen: number): string {
  return `${Math.floor(fen / 100)}.${String(fen % 100).padStart(2, "0")}`;
}

function mmss(s: number): string {
  const v = Math.max(0, Math.floor(s));
  return `${Math.floor(v / 60)}:${String(v % 60).padStart(2, "0")}`;
}

function CopyLink({ url }: { url: string }) {
  const [state, setState] = useState<"" | "ok" | "fail">("");
  return (
    <div className="flex w-full flex-col items-center gap-2">
      <Button variant="outline" onClick={async () => setState((await copyText(url)) ? "ok" : "fail")}>
        {state === "ok" ? <Check /> : <Copy />}
        {state === "ok" ? "复制好了，去微信里粘贴打开" : "复制这一页的网址"}
      </Button>
      {state === "fail" ? <p className="break-all text-xs text-foreground select-all">长按自己复制：{url}</p> : null}
    </div>
  );
}

const WECHAT_TEXT: Record<WechatPhase, string> = {
  idle: "点下面的按钮，在微信里付款",
  invoking: "微信付款窗口打开了，付完会回到这一页",
  ok: "微信说付好了，正在确认（一般几秒钟）",
  slow: "还没确认到这笔付款。微信里已经扣了钱就不用再付，这一页会自己查到；没扣钱就再付一次",
  cancel: "你取消了付款，没扣钱。想付的话再点一次",
  fail: "这次没付成，没扣钱。可以再试一次",
  nobridge: "这一页要在微信里打开才能用微信付款",
};

/**
 * 付款页：电脑扫码（微信 Native）、跳去支付宝、微信里直接付（JSAPI）、手机浏览器跳去微信付（H5）。
 * 付完这一页自己刷新出激活码（页面轮询）；微信说「付好了」、从微信跳回来都只是换一句话，以后端查到的为准。只吃 props。
 */
export function PayPanel({ view, secondsLeft, onFakePay, fakePaying, orderHref, wechat, oauth, h5, copyUrl }: PayPanelProps) {
  const closed = view.status === "closed" || secondsLeft <= 0;
  const kind = view.pay.kind;
  const isH5 = kind === "h5" || (kind === "redirect" && view.pay.payload.h5 === true);
  const waiting = !closed && !(kind === "oauth" && oauth?.message) && !(kind === "jsapi" && ["nobridge", "ok"].includes(wechat?.phase ?? ""));

  let body: ReactNode;
  if (closed) {
    body = (
      <div className="flex flex-col items-center gap-3 py-4">
        <p className="text-sm text-foreground">{view.message || "这个付款单过期关掉了，没付钱不会扣。"}</p>
        <Button asChild variant="outline">
          <a href={orderHref}>重新下单</a>
        </Button>
      </div>
    );
  } else if (kind === "qr") {
    body = (
      <>
        <div className="rounded-md border p-2">
          <QrCode rows={view.pay.payload.qr ?? []} label={`用${view.pay.method_label.replace("扫码", "")}扫码付款`} />
        </div>
        <p className="text-sm text-foreground">打开微信，扫一扫上面的二维码付款</p>
        <p className="text-xs text-muted-foreground">二维码 {mmss(secondsLeft)} 后失效 · 付完这一页会自己刷新出激活码</p>
      </>
    );
  } else if (kind === "jsapi" && wechat) {
    body = (
      <>
        <p className="inline-flex items-center gap-2 text-sm text-foreground" data-testid="wechat-phase" data-phase={wechat.phase}>
          {wechat.phase === "ok" ? <Loader2 className="size-4 animate-spin" /> : null}
          {WECHAT_TEXT[wechat.phase]}
        </p>
        {wechat.phase === "nobridge" ? (
          copyUrl ? <CopyLink url={copyUrl} /> : null
        ) : wechat.phase === "ok" ? null : (
          <Button size="lg" className="h-11 w-full max-w-xs text-[15px]" disabled={wechat.phase === "invoking"} onClick={wechat.onPay}>
            {wechat.phase === "invoking" ? <Loader2 className="animate-spin" /> : null}
            {wechat.phase === "idle" || wechat.phase === "invoking" ? "微信支付" : "再付一次"}
          </Button>
        )}
        <p className="text-xs text-muted-foreground">付款单 {mmss(secondsLeft)} 后失效</p>
      </>
    );
  } else if (kind === "oauth" && oauth) {
    body = oauth.message ? (
      <>
        <p className="text-sm leading-relaxed text-foreground" data-testid="oauth-message">{oauth.message}</p>
        {oauth.retry !== false ? (
          <Button asChild size="lg" className="h-11 w-full max-w-xs text-[15px]">
            <a href={oauth.href}>
              <RefreshCw />
              再试一次
            </a>
          </Button>
        ) : null}
        {copyUrl ? <CopyLink url={copyUrl} /> : null}
      </>
    ) : (
      <p className="inline-flex items-center gap-2 text-sm text-foreground">
        <Loader2 className="size-4 animate-spin" />
        正在打开微信付款……
      </p>
    );
  } else if (isH5 && h5) {
    body = (
      <>
        <p className="text-sm text-foreground">会跳到微信去付，付完回到这一页</p>
        <Button size="lg" className="h-11 w-full max-w-xs text-[15px]" disabled={h5.busy} onClick={h5.onOpen}>
          {h5.busy ? <Loader2 className="animate-spin" /> : <ExternalLink />}
          打开微信付款
        </Button>
        <Button variant="outline" onClick={h5.onCheck}>
          我已经付了，查一下
        </Button>
        {h5.error ? <p className="text-sm text-destructive">{h5.error}</p> : null}
        <p className="text-xs text-muted-foreground">付款单 {mmss(secondsLeft)} 后失效 · 手机上要装了微信才能跳过去</p>
      </>
    );
  } else if (kind === "redirect" && view.pay.payload.url) {
    body = (
      <>
        <p className="text-sm text-foreground">去{view.pay.method_label}付款，付完回到这一页</p>
        <Button asChild size="lg" className="h-11 px-8">
          <a href={view.pay.payload.url}>
            去{view.pay.method_label}付款
            <ExternalLink />
          </a>
        </Button>
        <p className="text-xs text-muted-foreground">付款单 {mmss(secondsLeft)} 后失效</p>
      </>
    );
  } else {
    body = <p className="text-sm text-muted-foreground">付款方式没准备好，回去换一种。</p>;
  }

  return (
    <div className="mx-auto flex max-w-xl flex-col gap-6 px-4 py-10 sm:px-6">
      <div className="flex flex-col gap-1">
        <h1 className="font-display text-3xl leading-tight font-bold tracking-wide text-foreground">付款</h1>
        <p className="text-sm text-body">
          {view.sku_name}
          {view.addons.length ? ` + ${view.addons.map((a) => a.name).join("、")}` : ""}
        </p>
      </div>

      <div className="flex flex-col items-center gap-4 rounded-lg border px-5 py-7 text-center">
        <div className="flex items-baseline gap-1">
          <span className="text-sm text-body">应付</span>
          <span className="text-3xl font-semibold text-price tabular-nums" data-testid="pay-amount">
            {yuan(view.total_fen)}
          </span>
          <span className="text-sm text-body">元</span>
        </div>

        {body}

        {waiting ? (
          <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground" aria-live="polite">
            <Loader2 className="size-3 animate-spin" />
            等你付款
          </span>
        ) : null}
      </div>

      {view.pay.simulated && !closed && onFakePay ? (
        <div className="flex flex-col items-start gap-2 rounded-lg border border-dashed px-4 py-3">
          <span className="text-xs text-muted-foreground">本机测试用的假网关（线上不会出现）</span>
          <Button variant="outline" size="sm" disabled={fakePaying} onClick={onFakePay}>
            {fakePaying ? <Loader2 className="animate-spin" /> : null}
            模拟付款
          </Button>
        </div>
      ) : null}

      <p className="text-xs leading-relaxed text-muted-foreground">
        付款遇到问题、扣了钱没出激活码，不用重复付：这一页会自己去查，查到了就出激活码。
      </p>
    </div>
  );
}
