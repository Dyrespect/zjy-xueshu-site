/**
 * 账号和登录的接口（12 号设计）。只通过 api.ts 发请求。
 * 会话是后端发的 HttpOnly cookie（psy_sess），前端不碰它；页面靠 getSession() 知道登没登录、能用哪些登录方式。
 */
import { apiGet, apiPost } from "./api";
import { rememberChatKey, rememberedChatKey } from "./intake";
import type { AccountOrder, AccountOrders, AccountSession, LoginResult, OrderLink, QrStart, QrStatus, SmsSent } from "./account-types";

export * from "./account-types";

export const getSession = () => apiGet<AccountSession>("/channels/account/session");
export const logout = (all = false) => apiPost<{ ok: boolean; message: string }>("/channels/account/logout", { all });
export const skipPhone = () => apiPost<{ ok: boolean }>("/channels/account/phone/skip", {});
export const getMyOrders = () => apiGet<AccountOrders>("/channels/account/orders");
export const getMyOrder = (orderNo: string) => apiGet<AccountOrder>(`/channels/account/orders/${encodeURIComponent(orderNo)}`);

// ---------------- 登录

export const startQr = () => apiPost<QrStart>("/channels/login/qr", {});
export const pollQr = (scene: string) => apiGet<{ status: QrStatus }>(`/channels/login/qr/${encodeURIComponent(scene)}`);
/** 本机走查：假装手机扫了（只在假微信时后端才认） */
export const fakeScanQr = (scene: string) => apiPost<{ reply: string }>(`/channels/login/qr/${encodeURIComponent(scene)}/fake-scan`, {});
export const startSms = (phone: string, purpose: "login" | "bind" = "login") =>
  apiPost<SmsSent>("/channels/login/sms/start", { phone, purpose });
export const verifySms = (phone: string, code: string, purpose: "login" | "bind" = "login") =>
  apiPost<LoginResult>("/channels/login/sms/verify", { phone, code, purpose });

/** 微信里静默登录：整页跳去后端，后端去服务号网页授权，回来落在 next。 */
export function wxLoginUrl(next: string): string {
  return `/api/channels/login/wx?next=${encodeURIComponent(next)}`;
}

const NO_AUTO = "xshb.account.noauto";

/** 微信里退出后，本页面会话内不再自动静默登录（不然一退就又登上了）。 */
export function suppressAutoLogin(on: boolean): void {
  try {
    if (on) window.sessionStorage.setItem(NO_AUTO, "1");
    else window.sessionStorage.removeItem(NO_AUTO);
  } catch {
    /* 存不了就算了 */
  }
}

function autoSuppressed(): boolean {
  try {
    return window.sessionStorage.getItem(NO_AUTO) === "1";
  } catch {
    return false;
  }
}

/** 地址里的 login=wx_xxx（微信登录失败退回来的原因）。 */
export function loginError(): string {
  try {
    return new URLSearchParams(window.location.search).get("login") ?? "";
  } catch {
    return "";
  }
}

const LOGIN_ERRORS: Record<string, string> = {
  wx_state: "微信登录没对上，再试一次。",
  wx_denied: "没拿到微信的授权，再试一次，或者换手机号登录。",
  wx_fail: "微信那边没响应，过一会儿再试，或者换手机号登录。",
  wx_snapshot: "现在是微信的预览页：点页面下方「访问完整网页」再登录。",
  wx_notwechat: "微信登录要在微信里打开这个网页；在这里可以用别的方式登录。",
  wx_off: "微信登录还没开通，用别的方式登录。",
};

export function loginErrorText(code: string): string {
  return LOGIN_ERRORS[code] ?? "";
}

/** 微信里、没登录、微信登录开着、地址里没有出错标记、没退出过：整页跳去静默登录。跳了返回 true。 */
export function maybeAutoWxLogin(s: AccountSession, next: string): boolean {
  if (s.logged_in || s.device !== "wechat" || !s.methods.includes("wx") || loginError() || autoSuppressed()) return false;
  window.location.href = wxLoginUrl(next);
  return true;
}

/** 当前页面的站内路径（登录完回这里），去掉 login= 出错标记。 */
export function currentPath(): string {
  const u = new URL(window.location.href);
  u.searchParams.delete("login");
  return u.pathname + (u.search || "");
}

/**
 * 登录后：把这台设备上存着的聊天会话归到我名下（匿名的才归，别人的不动），再把浏览器记的聊天 key 换成这个人最近的会话。
 */
export async function afterLogin(): Promise<AccountSession> {
  const key = rememberedChatKey();
  if (key) await apiPost("/channels/account/adopt", { key }).catch(() => undefined);
  const s = await getSession();
  if (s.chat_key) rememberChatKey(s.chat_key);
  suppressAutoLogin(false);
  return s;
}

export const getOrderLink = (q: { token?: string; chat_key?: string }) => apiGet<OrderLink>("/channels/account/order-link", q);
export const bindOrderLink = (q: { token?: string; chat_key?: string }) =>
  apiPost<{ ok: boolean; state: string; message: string }>("/channels/account/order-link", q);
