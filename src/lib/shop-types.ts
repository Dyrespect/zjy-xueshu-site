/**
 * 自有网页下单、付款、平台渠道（后台）的数据类型。跟后端 app/shop/router.py、app/platforms/router.py、
 * app/admin/shop_router.py、app/admin/platforms_router.py 的返回对上。价格全是后端从设置里算好的字符串。
 */

export interface ShopTier {
  key: string;
  name: string;
  min_minutes: number;
  max_minutes: number;
  max_pages: number;
  std_hours: number;
  rush_hours: number | null;
  rush: boolean;
  /** 篇数档 key → 价；null = 这一档不开放这个篇数 */
  prices: Record<string, string | null>;
}

export interface ShopBand {
  key: string;
  name: string;
  max_papers: number;
}

export interface ShopAddon {
  key: "rush" | "revision" | "find_refs" | string;
  name: string;
  price: string | null;
  note: string;
}

export interface PayMethod {
  method: string;
  label: string;
}

/** 资料清单的一样：东西 + 半句用来干什么 */
export interface MaterialItem {
  text: string;
  use: string;
}

/** 下单前准备好这些（订单中枢设置里的资料清单，/api/shop/catalog 的 materials）：按场合列必须发的、有的话更好的 */
export interface MaterialsGuideView {
  title: string;
  lead: string;
  must_title: string;
  nice_title: string;
  common_title: string;
  /** 资料齐了才开工、时限从哪儿算 */
  rule: string;
  /** 每个场合都要说的（讲几分钟、哪天汇报、学校名）；required = 开工前必须有 */
  common: (MaterialItem & { required: boolean })[];
  occasions: { key: string; name: string; must: MaterialItem[]; nice: MaterialItem[] }[];
}

export interface ShopCatalog {
  enabled: boolean;
  tiers: ShopTier[];
  bands: ShopBand[];
  addons: ShopAddon[];
  find_refs_extra_hours: number;
  revisions_included: number;
  auto_confirm_days: number;
  page_rule_text: string;
  /** 下单前准备好这些；旧后端没有这项 */
  materials?: MaterialsGuideView;
  methods: PayMethod[];
  ua_kind: "pc" | "mobile" | "wechat" | string;
  hint: string;
  /** online：有配好的付款方式；platforms：自有网页暂不收款（商户号没下来），「去付款」换成去小红书 / 闲鱼下单。旧后端没有这项 = online */
  pay_mode?: "online" | "platforms";
  /** 手机浏览器里没有能用的付款方式、但微信里能付（JSAPI 开了、微信 H5 没开）：给「复制网址到微信里打开」。旧后端没有这项 = false */
  open_in_wechat?: boolean;
  notices: string[];
  site_url: string;
  price_hash: string;
}

export interface OrderSelection {
  tier: string;
  band: string;
  rush: boolean;
  find_refs: boolean;
  extra_revisions: number;
}

export interface QuoteLine {
  key: string;
  name: string;
  price: string;
}

export interface ShopQuote {
  ok: boolean;
  why: string;
  sku: string;
  sku_name: string;
  base_price: string;
  addons: QuoteLine[];
  total: string;
  total_fen: number;
  hours: number;
  max_pages: number;
  rush_ok: boolean;
  rush_why: string;
  earliest_start: string | null;
  eta_date: string | null;
  queue_full: boolean;
  notes: string[];
}

export interface PayInfo {
  /**
   * qr 扫码（电脑）/ redirect 跳过去付（支付宝；微信 H5 时 payload.h5 = true）/ jsapi 微信里调起（payload 是调起参数）/
   * oauth 微信里还要先去服务号网页授权（payload.url）/ h5 手机浏览器，点「打开微信付款」时才去要链接
   */
  kind: "qr" | "redirect" | "jsapi" | "oauth" | "h5" | "";
  /** qr：{code_url, qr: 一行一个字符串的模块矩阵}；redirect：{url}；jsapi：{appId, timeStamp, nonceStr, package, signType, paySign} */
  payload: { code_url?: string; qr?: string[]; url?: string; [k: string]: unknown };
  method: string;
  method_label: string;
  simulated: boolean;
}

export interface CheckoutView {
  view_token: string;
  status: "pending" | "paid" | "closed" | "refunding" | "refunded" | "part_refunded" | string;
  status_label: string;
  total_fen: number;
  expires_at: string | null;
  paid_at: string | null;
  pay: PayInfo;
  code: string;
  redeem_url: string;
  sku_name: string;
  addons: QuoteLine[];
  hours: number;
  message: string;
}

export interface ClaimProduct {
  ok: boolean;
  platform: string;
  platform_label: string;
  title: string;
  sku_name: string;
  why: string;
}

export interface ClaimView {
  status: "pending" | "ok" | "rejected" | "problem" | "exists" | string;
  claim_token: string;
  code: string;
  redeem_url: string;
  message: string;
}

// ---------------- 后台 ----------------

export interface DueItem {
  kind: string;
  level: "high" | "mid" | "low" | string;
  title: string;
  detail: string;
  inbox_id?: number | null;
  order_id?: number | null;
  platform?: string;
  platform_label?: string;
  platform_order_id?: string;
  code?: string;
  action?: string;
  at?: string | null;
}

export interface ChannelProfile {
  platform: string;
  label: string;
  adapter: string;
  adapters: string[];
  enabled: boolean;
  mode: string;
  delivery_template: string;
  allow_url: boolean;
  remind_after_paid_hours: number;
  confirm: string[];
}

export interface ChannelProduct {
  id: number;
  platform: string;
  product_ref: string;
  title: string;
  sku: string;
  addons: string[];
  sku_name: string;
  listed_price: string;
  price: string;
  price_ok: boolean;
  token: string;
  link: string;
  active: boolean;
  note: string;
}

export interface SkuOption {
  sku: string;
  name: string;
  price: string;
}

export interface ChannelOverview {
  profiles: ChannelProfile[];
  products: ChannelProduct[];
  skus: SkuOption[];
  addons: { key: string; name: string; price: string }[];
}

export interface ManualEntryBody {
  platform: string;
  platform_order_id: string;
  product_id?: number | null;
  sku?: string;
  addons?: string[];
  paid_amount?: string;
  buyer_hint?: string;
}

export interface ManualEntryResult {
  exit: string;
  detail: string;
  inbox_id: number | null;
  order_id: number | null;
  code: string;
  text: string;
}

export interface InboxRow {
  id: number;
  platform: string;
  platform_label: string;
  source: string;
  platform_order_id: string;
  sku_name: string;
  paid_amount: string;
  buyer_hint: string;
  exit: string;
  exit_label: string;
  verify_status: string;
  order_id: number | null;
  code: string;
  text: string;
  pasted_at: string | null;
  completed_at: string | null;
  signals: { kind: string; at: string; exit: string }[];
  error: string;
  created_at: string;
  stage: string;
  stage_label: string;
  hold: boolean;
}

export type SignalKind = "completed" | "refund_requested" | "refund" | "refund_closed";

export interface WebOrderRow {
  id: number;
  out_trade_no: string;
  status: string;
  status_label: string;
  sku_name: string;
  addons: string[];
  amount: string;
  amount_fen: number;
  paid_fen: number;
  refunded_fen: number;
  method: string;
  pay_node: string;
  order_id: number | null;
  code: string;
  create_exit: string;
  ua_kind: string;
  source: string;
  created_at: string;
  paid_at: string | null;
  refunds: { id: number; amount: string; status: string; status_label: string; reason: string; scope: string; void_result: string; created_at: string }[];
}

export interface PayMethodStatus {
  method: string;
  label: string;
  node: string;
  missing: string[];
  ready: boolean;
  where: string;
}

export interface ShopStatus {
  enabled: boolean;
  fake: boolean;
  methods: PayMethodStatus[];
  timer: boolean;
  timer_minutes: number;
  auto_confirm_days: number;
  auto_confirm_platforms: string[];
  checkout_ttl_min: number;
  redeem_url: string;
}
