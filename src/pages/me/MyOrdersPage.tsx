import { useCallback, useEffect, useState } from "react";

import { LoginBox } from "@/blocks/login-panel/load";
import { MyOrdersList, MyOrdersLogin } from "@/blocks/my-orders";
import { PhoneBindBox } from "@/blocks/phone-bind/load";
import { SiteFrame } from "@/blocks/site-shell/load";
import {
  afterLogin,
  getMyOrders,
  getSession,
  logout,
  maybeAutoWxLogin,
  suppressAutoLogin,
  type AccountOrders,
  type AccountSession,
} from "@/lib/account";
import { startLogin, verifyLogin } from "@/lib/entry";
import NotFound from "@/pages/NotFound";

/**
 * /me 我的订单（12 号设计第七节）：登录后看这个账号下的所有订单（网页、微信客服认领的、合过来的）。
 * 微信里自动静默登录；电脑扫码或手机号；配了邮件服务的另有「订单号 + 邮箱」老入口。一种登录方式都没有时显示页面不存在。
 * 登录了、没绑手机号、短信开着：账号下面出「绑定手机号」。
 */
export function MyOrdersPage() {
  const [session, setSession] = useState<AccountSession | null>(null);
  const [data, setData] = useState<AccountOrders | null>(null);
  const [failed, setFailed] = useState(false);

  const load = useCallback((s: AccountSession) => {
    setSession(s);
    if (s.logged_in) getMyOrders().then(setData, () => setData(null));
    else setData(null);
  }, []);

  useEffect(() => {
    getSession()
      .then((s) => {
        if (maybeAutoWxLogin(s, "/me")) return;
        if (s.logged_in) void afterLogin().then(load);
        else load(s);
      })
      .catch(() => setFailed(true));
  }, [load]);

  if (failed) return <NotFound />;
  if (!session) return null;
  const canLogin = session.methods.length > 0 || session.email;
  if (!session.logged_in && !canLogin) return <NotFound />;

  const out = (all: boolean) => {
    if (session.device === "wechat") suppressAutoLogin(true);
    void logout(all).finally(() => getSession().then(load));
  };

  return (
    <SiteFrame gate={false} noindex cta={false} className="text-base">
      {session.logged_in && data ? (
        <MyOrdersList masked={data.label || session.label} orders={data.orders} onLogout={() => out(false)} onLogoutAll={() => out(true)}>
          {session.sms && !session.phone_bound ? (
            <PhoneBindBox compact skippable={false} onDone={() => getSession().then(load)} />
          ) : null}
        </MyOrdersList>
      ) : !session.logged_in ? (
        <div className="mx-auto flex max-w-md flex-col gap-8 px-4 py-10 sm:px-6">
          <div className="flex flex-col gap-2">
            <h1 className="font-display text-3xl leading-tight font-bold tracking-wide text-foreground">我的订单</h1>
            <p className="text-[15px] leading-relaxed text-body">登录以后，看你所有订单的进度、交付页和发票。</p>
          </div>
          {session.methods.length ? <LoginBox session={session} next="/me" onLoggedIn={load} /> : null}
          {session.email ? (
            <div className={session.methods.length ? "border-t pt-6" : ""}>
              <MyOrdersLogin
                embedded
                onStart={startLogin}
                onVerify={(orderNo, email, code, challenge) =>
                  verifyLogin(orderNo, email, code, challenge).then(() => afterLogin().then(load))
                }
              />
            </div>
          ) : null}
        </div>
      ) : null}
    </SiteFrame>
  );
}
