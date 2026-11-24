import { Loader2 } from "lucide-react";
import { useState, type FormEvent } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export interface LoginFormProps {
  onSubmit: (password: string) => Promise<void>;
}

/** 后台登录：一个密码（只有 Edison 用）。 */
export function LoginForm({ onSubmit }: LoginFormProps) {
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!password || busy) return;
    setBusy(true);
    setError("");
    try {
      await onSubmit(password);
    } catch (err) {
      setError(err instanceof Error ? err.message : "没登进去");
    } finally {
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="mx-auto flex w-full max-w-xs flex-col gap-4">
      <h1 className="text-xl font-semibold text-foreground">后台登录</h1>
      <Input
        type="password"
        autoFocus
        autoComplete="current-password"
        aria-label="密码"
        placeholder="密码"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      {error ? <p className="-mt-2 text-sm text-destructive">{error}</p> : null}
      <Button type="submit" disabled={!password || busy}>
        {busy ? <Loader2 className="animate-spin" /> : null}
        登录
      </Button>
    </form>
  );
}
