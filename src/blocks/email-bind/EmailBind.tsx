import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import type { SentCode } from "@/lib/entry-types";

export interface EmailBindProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** 发验证码（返回挑战，验证时带回去） */
  onStart: (email: string) => Promise<SentCode>;
  onVerify: (email: string, code: string, challenge: string) => Promise<unknown>;
  /** 绑好了 */
  onDone?: (masked: string) => void;
}

/** 留邮箱（可选）：填邮箱 → 收验证码 → 绑好，以后凭订单号 + 邮箱在「我的订单」查。只吃 props，接口由页面传进来。 */
export function EmailBind({ open, onOpenChange, onStart, onVerify, onDone }: EmailBindProps) {
  const [email, setEmail] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState<SentCode | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const run = (p: Promise<unknown>) => {
    setBusy(true);
    setError("");
    return p.catch((e) => setError(e instanceof Error ? e.message : "没成功，再试一次")).finally(() => setBusy(false));
  };
  const start = (e: FormEvent) => {
    e.preventDefault();
    void run(onStart(email.trim()).then(setSent));
  };
  const verify = (e: FormEvent) => {
    e.preventDefault();
    if (!sent) return;
    void run(
      onVerify(email.trim(), code.trim(), sent.challenge).then(() => {
        onDone?.(sent.masked);
        onOpenChange(false);
        setSent(null);
        setCode("");
      }),
    );
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>留个邮箱（可选）</DialogTitle>
          <DialogDescription>
            以后凭订单号和这个邮箱，就能在「我的订单」查进度、找交付页和发票。不留也不影响做单。
          </DialogDescription>
        </DialogHeader>
        {!sent ? (
          <form onSubmit={start} className="flex flex-col gap-3">
            <label htmlFor="bind-email" className="text-sm text-foreground">
              邮箱
            </label>
            <Input id="bind-email" type="email" inputMode="email" autoComplete="email" required value={email}
              onChange={(e) => setEmail(e.target.value)} placeholder="name@example.edu.cn" />
            <Button type="submit" disabled={busy || !email.trim()}>
              {busy ? "正在发……" : "发验证码"}
            </Button>
          </form>
        ) : (
          <form onSubmit={verify} className="flex flex-col gap-3">
            <p className="text-sm text-body">{sent.message}</p>
            <label htmlFor="bind-code" className="text-sm text-foreground">
              验证码
            </label>
            <Input id="bind-code" inputMode="numeric" autoComplete="one-time-code" required value={code}
              onChange={(e) => setCode(e.target.value)} placeholder="6 位数字" className="font-mono tracking-widest" />
            <Button type="submit" disabled={busy || code.trim().length < 4}>
              {busy ? "正在核对……" : "绑好"}
            </Button>
            <button type="button" className="self-start text-xs text-muted-foreground hover:text-foreground" onClick={() => setSent(null)}>
              换个邮箱
            </button>
          </form>
        )}
        {error ? (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        ) : null}
      </DialogContent>
    </Dialog>
  );
}
