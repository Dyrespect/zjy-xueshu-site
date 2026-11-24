import { useEffect, useState } from "react";

import { bindOrderLink, currentPath, getOrderLink, type OrderLink } from "@/lib/account";

import { AccountBanner } from "./AccountBanner";

export interface AccountBannerBoxProps {
  /** 交付令牌（交付页、需求卡）或聊天 key（聊天页），给一个 */
  token?: string;
  chatKey?: string;
  className?: string;
}

/** 自己取数的那一条：问后端这单和当前登录的人什么关系，没登录给「登录」、匿名的单给「记到我的账号」。 */
export function AccountBannerBox({ token, chatKey, className }: AccountBannerBoxProps) {
  const [link, setLink] = useState<OrderLink | null>(null);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    if (!token && !chatKey) return;
    getOrderLink(token ? { token } : { chat_key: chatKey }).then(setLink, () => setLink(null));
  }, [token, chatKey]);
  if (!link || (link.state !== "login" && link.state !== "bind" && !done)) return null;
  return (
    <div className={className}>
      <AccountBanner
        state={link.state}
        loginHref={`/login?next=${encodeURIComponent(currentPath())}`}
        busy={busy}
        done={done}
        error={error}
        onBind={() => {
          setBusy(true);
          setError("");
          bindOrderLink(token ? { token } : { chat_key: chatKey })
            .then((r) => setDone(r.message))
            .catch((e) => setError(e instanceof Error ? e.message : "没记上，再试一次"))
            .finally(() => setBusy(false));
        }}
      />
    </div>
  );
}
