/**
 * 匿名访客号和来源（模块 L 记来源用）。不登录、不收集个人信息：只是一串随机号，存在这台浏览器里。
 * 存储拿不到（无痕窗口、禁用了站点数据）时当新访客，页面照常用。
 */
const KEY = "psy-visitor";
const SRC_KEY = "psy-first-src";
let memo = "";

function randomId(): string {
  const c = globalThis.crypto;
  if (c && "randomUUID" in c) return `v${c.randomUUID().replace(/-/g, "").slice(0, 24)}`;
  return `v${Math.random().toString(36).slice(2)}${Date.now().toString(36)}`.slice(0, 25);
}

export function getVisitor(): string {
  if (memo) return memo;
  try {
    const saved = localStorage.getItem(KEY);
    if (saved && /^[A-Za-z0-9_-]{8,40}$/.test(saved)) return (memo = saved);
    memo = randomId();
    localStorage.setItem(KEY, memo);
  } catch {
    memo = memo || randomId();
  }
  return memo;
}

/** 链接里的 from（来源）和 s（转发人的分享码）；第一次带来源进来时记下，之后领图库也挂这个来源。 */
export function readLanding(search: string): { src: string; share: string } {
  const p = new URLSearchParams(search);
  const src = (p.get("from") ?? "").slice(0, 32);
  const share = (p.get("s") ?? "").slice(0, 12);
  try {
    if (src && !sessionStorage.getItem(SRC_KEY)) sessionStorage.setItem(SRC_KEY, src);
  } catch {
    /* 存不了就算了 */
  }
  return { src, share };
}

export function firstSource(): string {
  try {
    return sessionStorage.getItem(SRC_KEY) ?? "";
  } catch {
    return "";
  }
}
