/** 账号和登录（/api/channels/account/*、/api/channels/login/*；docs/任务单/12_登录与正规化_设计.md）。跟后端 app/channels/account.py、login_web.py 对上。 */

export type LoginMethod = "wx" | "qr" | "sms";

export interface AccountSession {
  logged_in: boolean;
  /** wx 微信里静默 / qr 电脑扫码 / sms 手机号 / email 订单号 + 邮箱 */
  method: string;
  /** 「微信」「手机 138****5678」 */
  label: string;
  /** 打码的手机号 */
  phone: string;
  phone_bound: boolean;
  /** 该不该提示绑手机号（登录了、没绑、短信开着、7 天内没点过「先不绑」） */
  prompt_phone: boolean;
  /** 这台设备能用的登录方式（推荐顺序） */
  methods: LoginMethod[];
  device: "wechat" | "mobile" | "pc" | string;
  /** 短信开着没有：关着时页面上不出现任何手机号入口 */
  sms: boolean;
  /** 「订单号 + 邮箱」老入口开着没有 */
  email: boolean;
  /** 认领前要不要先登录 */
  login_required: boolean;
  /** 这个人最近的网页聊天会话 */
  chat_key: string;
}

export interface QrStart {
  scene: string;
  image: string;
  expires_in: number;
  fake: boolean;
}

export type QrStatus = "pending" | "ok" | "expired" | "used";

export interface SmsSent {
  masked: string;
  message: string;
  ttl_min: number;
}

export interface LoginResult {
  ok: boolean;
  masked: string;
  merged: boolean;
  message: string;
}

/** 交付页、需求卡、聊天页顶上那一条：login 没登录 / bind 可以记到我的账号 / mine 已经是我的 / none 不显示 */
export interface OrderLink {
  state: "login" | "bind" | "mine" | "none";
  methods: LoginMethod[];
}

export interface AccountOrder {
  order_no: string;
  sku_name: string;
  stage: string;
  stage_label: string;
  progress: string;
  claimed_at: string | null;
  delivery_path: string;
  brief_path: string | null;
  chat_path: string | null;
  invoice_hint: string;
}

export interface AccountOrders {
  masked: string;
  label: string;
  orders: AccountOrder[];
}
