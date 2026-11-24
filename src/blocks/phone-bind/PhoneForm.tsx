import { useEffect, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { SmsSent } from "@/lib/account-types";

export interface PhoneFormProps {
  /** 发验证码（后端过四道限流；不成功 reject，message 是后端的中文说明） */
  onStart: (phone: string) => Promise<SmsSent>;
  /** 填码核对 */
  onVerify: (phone: string, code: string) => Promise<unknown>;
  submitLabel?: string;
  /** 输入框 id 前缀（同一页上有两个时区分） */
  idPrefix?: string;
}

/** 手机号 + 短信验证码（登录、绑定共用）。60 秒内不能再发；只吃 props。只在短信开着时出现（规矩 23）。 */
export function PhoneLogin({ onStart, onVerify, submitLabel = "登录", idPrefix = "phone" }: PhoneFormProps) {
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState<SmsSent | null>(null);
  const [wait, setWait] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (wait <= 0) return;
    const t = window.setTimeout(() => setWait((w) => w - 1), 1000);
    return () => window.clearTimeout(t);
  }, [wait]);

  const run = (p: Promise<unknown>) => {
    setBusy(true);
    setError("");
    return p.catch((e) => setError(e instanceof Error ? e.message : "没成功，再试一次")).finally(() => setBusy(false));
  };
  const send = () => {
    void run(onStart(phone.trim()).then((s) => {
      setSent(s);
      setWait(60);
    }));
  };
  const verify = (e: FormEvent) => {
    e.preventDefault();
    if (sent) void run(onVerify(phone.trim(), code.trim()));
  };
  const okPhone = /^\s*(\+?86)?[\s-]*1[3-9]\d[\s-]*\d{4}[\s-]*\d{4}\s*$/.test(phone);

  return (
    <form onSubmit={verify} className="flex flex-col gap-3">
      <div className="flex flex-col gap-1.5">
        <label htmlFor={`${idPrefix}-number`} className="text-sm text-foreground">手机号</label>
        <div className="flex gap-2">
          <Input id={`${idPrefix}-number`} type="tel" inputMode="numeric" autoComplete="tel" value={phone}
            onChange={(e) => setPhone(e.target.value)} placeholder="中国大陆 11 位手机号" className="h-11 flex-1" />
          <Button type="button" variant="outline" className="h-11 w-28 shrink-0" disabled={busy || !okPhone || wait > 0} onClick={send}>
            {wait > 0 ? `${wait} 秒后重发` : sent ? "重新获取" : "获取验证码"}
          </Button>
        </div>
      </div>
      {sent ? <p className="text-xs leading-relaxed text-muted-foreground">{sent.message}</p> : null}
      <div className="flex flex-col gap-1.5">
        <label htmlFor={`${idPrefix}-code`} className="text-sm text-foreground">验证码</label>
        <Input id={`${idPrefix}-code`} inputMode="numeric" autoComplete="one-time-code" maxLength={6} value={code}
          onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} placeholder="6 位数字" className="h-11 font-mono tracking-widest" />
      </div>
      <Button type="submit" size="lg" className="h-11" disabled={busy || !sent || code.length !== 6}>
        {busy && sent ? "正在核对……" : submitLabel}
      </Button>
      {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
    </form>
  );
}

export interface PhoneBindProps extends PhoneFormProps {
  /** 先不绑（7 天内需求卡不再弹） */
  onSkip?: () => void;
  /** 小一号（放在「我的订单」里那一行） */
  compact?: boolean;
}

/** 绑定手机号的提示卡：一次就好，可以先不绑。只吃 props。 */
export function PhoneBind({ onSkip, compact, ...form }: PhoneBindProps) {
  return (
    <section className="flex flex-col gap-4 rounded-lg border px-5 py-5" data-testid="phone-bind">
      <div className="flex flex-col gap-1">
        <h2 className={compact ? "text-[15px] font-semibold text-foreground" : "text-lg font-semibold text-foreground"}>绑定手机号</h2>
        <p className="text-sm leading-relaxed text-body">
          绑一次就好：换了手机、换了电脑，用手机号也能登录、找到你的订单；售后时我们能联系到你。
        </p>
      </div>
      <PhoneLogin {...form} submitLabel="绑定" idPrefix={form.idPrefix ?? "bind"} />
      {onSkip ? (
        <button type="button" onClick={onSkip} className="self-start text-xs text-muted-foreground hover:text-foreground">
          先不绑，以后在「我的订单」里也能绑
        </button>
      ) : null}
    </section>
  );
}
