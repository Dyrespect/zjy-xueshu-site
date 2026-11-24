/**
 * 入口模块（D）的数据类型：兑换网页、「我的订单」、后台「入口」页。纯类型，不发请求，区块组件可以直接 import。
 * 字段照后端 app/channels/redeem.py、account.py、admin/entry_router.py。
 */

export type RedeemState =
  | "invalid"
  | "not_found"
  | "void"
  | "expired"
  | "unclaimed"
  | "yours"
  | "taken"
  | "taken_joinable"
  | "addon"
  | "legacy";

export interface RedeemAction {
  entry: string;
  kind: "claim_web" | "link" | "chat" | "retry";
  label: string;
  url: string | null;
  hint: string;
  primary: boolean;
}

export interface BuyPlace {
  label: string;
  text: string;
  url: string;
}

export interface RedeemView {
  state: RedeemState;
  code: string;
  code_tail: string;
  sku_name: string;
  hours: number | null;
  progress: string;
  stage_label: string;
  actions: RedeemAction[];
  buy: BuyPlace[];
  code_hint: string;
  site_url: string;
  /** 认领前要先登录（12 号设计）：页面先出登录框 */
  login_required?: boolean;
  logged_in?: boolean;
  /** 已登录的账号：「微信」「手机 138****5678」 */
  login_label?: string;
}

export interface ClaimWebResult {
  key: string;
  chat_path: string;
  state: string;
  /** 需求卡还没确认时有：认领完先去点选需求（09 需求引导），再回聊天 */
  brief_path?: string;
}

export interface SentCode {
  challenge: string;
  masked: string;
  message: string;
}

export interface MyOrder {
  order_no: string;
  sku_name: string;
  stage: string;
  stage_label: string;
  progress: string;
  claimed_at: string | null;
  delivery_path: string;
  chat_path: string | null;
  invoice_hint: string;
}

export interface MyOrders {
  masked: string;
  orders: MyOrder[];
}

export interface EntryConfig {
  wecom_enabled: boolean;
  /** 认领前要求登录（12 号设计；默认开） */
  login_required?: boolean;
  wecom_links: Record<string, string>;
  wecom_reserve_for_delivery: number;
  wecom_welcome_max_age_s: number;
  redeem_entries: string[];
  redeem_ip_hourly: number;
  web_visitor_ip_daily: number;
  buy_places: BuyPlace[];
  code_hint: string;
  site_url: string;
  confirm_phrases: string[];
}

export interface EntryAdmin {
  config: EntryConfig;
  wecom: {
    configured: Record<string, boolean>;
    client_ready: boolean;
    available: boolean;
    reason: string;
    callback_path: string;
  };
  email: { enabled: boolean; via: string };
  checklists: Record<string, unknown>;
  visitor: { daily: number; global_daily: number };
  entries: { node_id: string; label: string; channel: string }[];
}
