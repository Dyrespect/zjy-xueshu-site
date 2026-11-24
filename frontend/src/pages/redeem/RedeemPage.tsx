import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router";

import { FlowFrame } from "@/blocks/flow-shell/load";
import { LoginBox } from "@/blocks/login-panel/load";
import { RedeemCard } from "@/blocks/redeem-card";
import { afterLogin, getSession, logout, maybeAutoWxLogin, suppressAutoLogin, type AccountSession } from "@/lib/account";
import { ApiError } from "@/lib/api";
import { claimOnWeb, getRedeem, getRedeemMeta, type RedeemAction, type RedeemView } from "@/lib/entry";
import { rememberChatKey } from "@/lib/intake";

/**
 * /c/:code 兑换网页：第一步登录（12 号设计：微信里自动静默、电脑扫码、手机号），第二步认领到这个账号；码不能用说清楚为什么；
 * 页面上写清激活码从哪来。页头跟全站一样，页脚是精简的一行（blocks/flow-shell），地址里带码所以不让收录。
 * 这台设备一种登录方式都没有（或后台关了「认领前要求登录」）时照旧不登录认领。按钮来自后端的入口登记处。
 */
export function RedeemPage() {
  const { code = "" } = useParams();
  const navigate = useNavigate();
  const [view, setView] = useState<RedeemView | null>(null);
  const [session, setSession] = useState<AccountSession | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const here = code ? `/c/${encodeURIComponent(code)}` : "/c";

  const loadView = useCallback(() => {
    setError("");
    (code ? getRedeem(code) : getRedeemMeta())
      .then(setView)
      .catch((e) => {
        setError(e instanceof ApiError ? e.message : "查不到，稍后再试");
        getRedeemMeta().then((m) => setView({ ...m, state: code ? "not_found" : "invalid" }), () => undefined);
      });
  }, [code]);

  useEffect(() => {
    setView(null);
    getSession()
      .then((s) => {
        if (maybeAutoWxLogin(s, here)) return;
        setSession(s);
        if (s.logged_in) void afterLogin().then(setSession).finally(loadView);
        else loadView();
      })
      .catch(loadView);
  }, [here, loadView]);

  const act = (a: RedeemAction) => {
    setError("");
    if (a.kind === "claim_web") {
      setBusy(true);
      claimOnWeb(code)
        .then((r) => {
          rememberChatKey(r.key);
          navigate(r.brief_path || r.chat_path); // 需求卡没确认先去需求卡（09 需求引导）
        })
        .catch((e) => {
          if (e instanceof ApiError && e.status === 401) getSession().then(setSession).finally(loadView);
          setError(e instanceof Error ? e.message : "没认领上，再试一次");
        })
        .finally(() => setBusy(false));
    } else if (a.kind === "chat" && a.url) {
      navigate(a.url);
    } else if (a.kind === "link" && a.url) {
      window.location.href = a.url; // 微信客服链接：手机上会跳进微信
    } else if (a.kind === "retry") {
      navigate("/c");
    }
  };

  const loginSlot = session && !session.logged_in && session.methods.length ? (
    <LoginBox session={session} next={here} bare title="登录"
      onLoggedIn={(s) => {
        setSession(s);
        loadView();
      }} />
  ) : null;

  return (
    <FlowFrame className="text-base">
      <RedeemCard
        view={view}
        busy={busy}
        error={error}
        onAction={act}
        loginSlot={loginSlot}
        onSwitchAccount={() => {
          if (session?.device === "wechat") suppressAutoLogin(true);
          void logout().finally(() => getSession().then(setSession).finally(loadView));
        }}
        onSubmitCode={(c) => navigate(`/c/${encodeURIComponent(c.replace(/\s+/g, ""))}`)}
      />
    </FlowFrame>
  );
}
