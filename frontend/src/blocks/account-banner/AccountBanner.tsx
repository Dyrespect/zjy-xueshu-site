import { ArrowRight, Check } from "lucide-react";

import { AppLink } from "@/components/app-link";
import { Button } from "@/components/ui/button";
import type { OrderLink } from "@/lib/account-types";

export interface AccountBannerProps {
  /** login 没登录 / bind 可以记到我的账号 / mine、none 不显示 */
  state: OrderLink["state"];
  /** 去登录的地址（/login?next=这一页） */
  loginHref: string;
  onBind?: () => void;
  busy?: boolean;
  /** 记过来以后的一句话 */
  done?: string;
  error?: string;
}

/** 交付页、需求卡、聊天页顶上那一条：登录后把这一单记到你的账号（老链接照样能用，只是提示）。只吃 props。 */
export function AccountBanner({ state, loginHref, onBind, busy, done, error }: AccountBannerProps) {
  if (done) {
    return (
      <p className="flex items-center gap-2 rounded-lg border px-4 py-3 text-sm text-body" data-testid="account-banner">
        <Check className="size-4 shrink-0 text-primary" />
        {done}
      </p>
    );
  }
  if (state !== "login" && state !== "bind") return null;
  return (
    <div className="flex flex-col gap-3 rounded-lg border px-4 py-3 sm:flex-row sm:items-center sm:justify-between" data-testid="account-banner">
      <p className="text-sm leading-relaxed text-body">
        {state === "login"
          ? "登录后，这一单记在你的账号下：换手机、换电脑都能在「我的订单」里找到，开发票也方便。"
          : "这一单还没记到你的账号下：记过来以后，在「我的订单」里就能看到。"}
      </p>
      {state === "login" ? (
        <Button asChild size="sm" className="shrink-0 self-start sm:self-auto">
          <AppLink href={loginHref}>
            登录
            <ArrowRight />
          </AppLink>
        </Button>
      ) : (
        <Button size="sm" className="shrink-0 self-start sm:self-auto" disabled={busy} onClick={onBind}>
          {busy ? "正在记……" : "记到我的账号"}
        </Button>
      )}
      {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
    </div>
  );
}
