import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import { afterLogin, fakeScanQr, loginError, loginErrorText, pollQr, startQr, startSms, verifySms, wxLoginUrl,
  type AccountSession } from "@/lib/account";

import { LoginPanel, type QrState } from "./LoginPanel";

export interface LoginBoxProps {
  session: AccountSession;
  /** 登录完回哪（微信静默授权整页跳走，回来落在这里） */
  next: string;
  title?: string;
  lead?: ReactNode;
  bare?: boolean;
  /** 登录成功（扫码、手机号；微信是整页跳走回来，不走这里） */
  onLoggedIn: (s: AccountSession) => void;
}

/** 自己调接口的登录框：扫码（建码、每 2 秒问一次、过期换新）、手机号、微信授权跳转。 */
export function LoginBox({ session, next, title, lead, bare, onLoggedIn }: LoginBoxProps) {
  const [qr, setQr] = useState<QrState | null>(null);
  const scene = useRef("");
  const done = useRef(false);
  const methods = session.methods;

  const finish = useCallback(() => {
    if (done.current) return;
    done.current = true;
    void afterLogin().then(onLoggedIn);
  }, [onLoggedIn]);

  const newQr = useCallback(() => {
    setQr({ image: "", status: "loading" });
    startQr()
      .then((q) => {
        scene.current = q.scene;
        setQr({ image: q.image, status: "pending", fake: q.fake });
      })
      .catch((e) => setQr({ image: "", status: "error", message: e instanceof Error ? e.message : "" }));
  }, []);

  // 电脑上一打开就出码（扫码是这台设备的第一个方式时）
  useEffect(() => {
    if (methods[0] === "qr") newQr();
  }, [methods, newQr]);

  useEffect(() => {
    if (!qr || qr.status !== "pending") return;
    const t = window.setInterval(() => {
      if (!scene.current) return;
      pollQr(scene.current)
        .then((r) => {
          if (r.status === "ok") finish();
          else if (r.status !== "pending") setQr((q) => (q ? { ...q, status: r.status } : q));
        })
        .catch(() => setQr((q) => (q ? { ...q, status: "expired" } : q)));
    }, 2000);
    return () => window.clearInterval(t);
  }, [qr, finish]);

  return (
    <LoginPanel
      methods={methods}
      title={title}
      lead={lead}
      bare={bare}
      error={loginErrorText(loginError())}
      onWx={() => {
        window.location.href = wxLoginUrl(next);
      }}
      qr={qr}
      onQrStart={newQr}
      onQrRefresh={newQr}
      onFakeScan={() => void fakeScanQr(scene.current).catch(() => undefined)}
      onSmsStart={(phone) => startSms(phone, "login")}
      onSmsVerify={(phone, code) => verifySms(phone, code, "login").then(finish)}
    />
  );
}
