/**
 * 客户这边（网页聊天、交付页）的数据类型和格式化小工具。纯函数、不发请求，区块组件可以直接 import。
 */

export interface ChatFile {
  id: number;
  name: string;
  size: number;
  url: string;
}

export interface ChatMessage {
  id: number;
  sender: "me" | "bot" | "edison";
  kind: string;
  text: string;
  /** 固定内容：terms 交付和注意事项、payment 付款方式、owner_qr 负责人微信二维码、pay_qr 付款二维码 */
  card: string | null;
  file: ChatFile | null;
  image_url: string | null;
  created_at: string;
}

export interface WebOrder {
  order_no: string;
  sku_name: string;
  stage: string;
  stage_label: string;
}

export interface WebChat {
  key: string;
  welcome: string;
  status: string;
  delivery_path: string | null;
  messages: ChatMessage[];
  /** 这个人在走的单（认领了才有） */
  order?: WebOrder | null;
  /** 这单的需求卡（09 需求引导）：在哪、确认了没有、顶上那一条写什么 */
  brief?: { path: string; confirmed: boolean; text: string } | null;
  /** 「我的订单」：配了邮件服务才开；绑过邮箱就不再提示 */
  account_enabled?: boolean;
  email_bound?: boolean;
  /** 顶上一直挂着的一行：回复由 AI 生成（接待机器人，法规要求的显式标识） */
  notice?: string;
  /** 小鱼正在打字（有排了时间、还没到点的回复） */
  typing?: boolean;
}

export interface OkMessage {
  ok: boolean;
  message: string;
}

// ---------------- 小工具 ----------------

export function fileSize(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

const WEEK = "日一二三四五六";

/** 2026-11-19 → 11月19日（周四） */
export function cnDate(iso: string | null | undefined, withWeekday = true): string {
  if (!iso) return "";
  const [y, m, d] = iso.slice(0, 10).split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  const base = `${m}月${d}日`;
  return withWeekday ? `${base}（周${WEEK[dt.getDay()]}）` : base;
}

/** 消息时间：今天只显示时:分，否则 月-日 时:分（按浏览器所在时区） */
export function msgTime(iso: string): string {
  const t = new Date(iso);
  const now = new Date();
  const hm = `${String(t.getHours()).padStart(2, "0")}:${String(t.getMinutes()).padStart(2, "0")}`;
  if (t.toDateString() === now.toDateString()) return hm;
  return `${t.getMonth() + 1}月${t.getDate()}日 ${hm}`;
}
