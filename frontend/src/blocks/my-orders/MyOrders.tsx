import { ArrowRight } from "lucide-react";
import { useState, type FormEvent, type ReactNode } from "react";

import { AppLink } from "@/components/app-link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { AccountOrder } from "@/lib/account-types";
import type { SentCode } from "@/lib/entry-types";

export interface MyOrdersLoginProps {
  onStart: (orderNo: string, email: string) => Promise<SentCode>;
  onVerify: (orderNo: string, email: string, code: string, challenge: string) => Promise<unknown>;
  /** 放在登录框下面当「老入口」时不要大标题 */
  embedded?: boolean;
}

/** 老入口：凭订单号 + 留过的邮箱收验证码登录（配了邮件服务才有）。只吃 props。 */
export function MyOrdersLogin({ onStart, onVerify, embedded }: MyOrdersLoginProps) {
  const [orderNo, setOrderNo] = useState("");
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState<SentCode | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const run = (p: Promise<unknown>) => {
    setBusy(true);
    setError("");
    void p.catch((e) => setError(e instanceof Error ? e.message : "没成功，再试一次")).finally(() => setBusy(false));
  };
  const start = (e: FormEvent) => {
    e.preventDefault();
    run(onStart(orderNo.trim(), email.trim()).then(setSent));
  };
  const verify = (e: FormEvent) => {
    e.preventDefault();
    if (sent) run(onVerify(orderNo.trim(), email.trim(), code.trim(), sent.challenge));
  };
  return (
    <div className={embedded ? "flex flex-col gap-4" : "mx-auto flex max-w-md flex-col gap-6 px-4 py-10 sm:px-6"}>
      <div className="flex flex-col gap-2">
        {embedded ? (
          <h2 className="text-[15px] font-semibold text-foreground">留过邮箱的老客户</h2>
        ) : (
          <h1 className="font-display text-3xl leading-tight font-bold tracking-wide text-foreground">我的订单</h1>
        )}
        <p className="text-[15px] leading-relaxed text-body">
          填订单号和你在聊天里留过的邮箱，收一个验证码就能登录，看所有订单的进度、交付页和发票。
        </p>
      </div>
      {!sent ? (
        <form onSubmit={start} className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="me-order" className="text-sm text-foreground">订单号</label>
            <Input id="me-order" inputMode="numeric" required value={orderNo} onChange={(e) => setOrderNo(e.target.value)}
              placeholder="例如 00012（交付页、水印上都有）" className="h-11" />
          </div>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="me-email" className="text-sm text-foreground">邮箱</label>
            <Input id="me-email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)}
              placeholder="name@example.edu.cn" className="h-11" />
          </div>
          <Button type="submit" size="lg" className="h-11" disabled={busy || !orderNo.trim() || !email.trim()}>
            {busy ? "正在发……" : "发验证码"}
          </Button>
        </form>
      ) : (
        <form onSubmit={verify} className="flex flex-col gap-4">
          <p className="rounded-md bg-card px-4 py-3 text-sm leading-relaxed text-body">{sent.message}</p>
          <div className="flex flex-col gap-1.5">
            <label htmlFor="me-code" className="text-sm text-foreground">验证码</label>
            <Input id="me-code" inputMode="numeric" autoComplete="one-time-code" required value={code}
              onChange={(e) => setCode(e.target.value)} placeholder="6 位数字" className="h-11 font-mono tracking-widest" />
          </div>
          <Button type="submit" size="lg" className="h-11" disabled={busy || code.trim().length < 4}>
            {busy ? "正在核对……" : "查看订单"}
          </Button>
          <button type="button" className="self-start text-xs text-muted-foreground hover:text-foreground" onClick={() => setSent(null)}>
            重新填订单号和邮箱
          </button>
        </form>
      )}
      {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
      {!embedded ? (
        <p className="border-t pt-5 text-xs leading-relaxed text-muted-foreground">
          没留过邮箱也没关系：回到当时的聊天网页，或者打开订单发货消息里的兑换网址，就能接着看。
        </p>
      ) : null}
    </div>
  );
}

export interface MyOrdersListProps {
  /** 账号那一行：「微信」「手机 138****5678」 */
  masked: string;
  orders: AccountOrder[];
  onLogout?: () => void;
  /** 所有设备都退出 */
  onLogoutAll?: () => void;
  /** 账号下面那一块（没绑手机号时放绑定手机号；短信没开时页面不放） */
  children?: ReactNode;
}

/** 我的订单：这个账号下的所有订单，每单一行：单号、货号、状态、进度、交付页、需求卡（没确认时）、回到聊天、开票说明。 */
export function MyOrdersList({ masked, orders, onLogout, onLogoutAll, children }: MyOrdersListProps) {
  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6 px-4 py-10 sm:px-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="flex flex-col gap-1">
          <h1 className="font-display text-3xl leading-tight font-bold tracking-wide text-foreground">我的订单</h1>
          <p className="text-sm text-muted-foreground" data-testid="my-account">已登录：{masked}</p>
        </div>
        <div className="flex gap-2">
          {onLogout ? <Button variant="outline" size="sm" onClick={onLogout}>退出</Button> : null}
          {onLogoutAll ? <Button variant="ghost" size="sm" onClick={onLogoutAll}>所有设备都退出</Button> : null}
        </div>
      </div>
      {children}
      {orders.length === 0 ? (
        <p className="rounded-lg border px-5 py-8 text-center text-sm leading-relaxed text-muted-foreground">
          这个账号下还没有订单。拿到激活码以后，打开兑换网址认领，就会出现在这里。
        </p>
      ) : (
        <ul className="flex flex-col gap-3">
          {orders.map((o) => (
            <li key={o.order_no} className="flex flex-col gap-3 rounded-lg border px-5 py-4" data-testid="my-order">
              <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                <span className="text-[15px] font-semibold text-foreground">
                  订单 {o.order_no} · {o.sku_name}
                </span>
                <span className="text-sm text-primary">{o.stage_label}</span>
              </div>
              <p className="text-sm leading-relaxed text-body">{o.progress}</p>
              <p className="text-xs text-muted-foreground">{o.invoice_hint}</p>
              <div className="flex flex-wrap gap-2">
                {o.brief_path ? (
                  <Button asChild size="sm">
                    <AppLink href={o.brief_path}>
                      去确认需求
                      <ArrowRight />
                    </AppLink>
                  </Button>
                ) : null}
                <Button asChild size="sm" variant={o.brief_path ? "outline" : "default"}>
                  <AppLink href={o.delivery_path}>
                    交付页
                    {o.brief_path ? null : <ArrowRight />}
                  </AppLink>
                </Button>
                {o.chat_path ? (
                  <Button asChild size="sm" variant="outline">
                    <AppLink href={o.chat_path}>回到聊天</AppLink>
                  </Button>
                ) : null}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
