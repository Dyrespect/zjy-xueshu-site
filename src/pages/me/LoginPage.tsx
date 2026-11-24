import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";

import { LoginBox } from "@/blocks/login-panel/load";
import { FlowFrame } from "@/blocks/flow-shell/load";
import { getSession, maybeAutoWxLogin, type AccountSession } from "@/lib/account";

/** 站内路径才回（跟后端 safe_next 同一个规矩）。 */
function safeNext(raw: string | null): string {
  const s = (raw ?? "").trim();
  return s.startsWith("/") && !s.startsWith("//") && !s.includes("\\") ? s : "/me";
}

/** /login?next=：交付页、聊天页顶上的「登录」点进来；登录完回 next。微信里自动静默登录。 */
export function LoginPage() {
  const [params] = useSearchParams();
  const next = safeNext(params.get("next"));
  const navigate = useNavigate();
  const [session, setSession] = useState<AccountSession | null>(null);

  useEffect(() => {
    getSession().then((s) => {
      if (s.logged_in) return navigate(next, { replace: true });
      if (maybeAutoWxLogin(s, next)) return;
      setSession(s);
    }, () => setSession(null));
  }, [navigate, next]);

  return (
    <FlowFrame className="text-base">
      <div className="mx-auto flex max-w-md flex-col gap-6 px-4 py-10 sm:px-6">
        {session && session.methods.length ? (
          <LoginBox session={session} next={next} title="登录" lead="登录以后，订单记在你的账号下：换手机、换电脑都能找到，开发票也方便。"
            onLoggedIn={() => navigate(next, { replace: true })} />
        ) : session ? (
          <p className="text-sm leading-relaxed text-body">登录还没开通。订单照样能凭交付页链接、聊天网址看。</p>
        ) : null}
      </div>
    </FlowFrame>
  );
}
