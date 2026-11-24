/**
 * 后台接单这一块的数据类型（跟 backend/app/admin/intake_router.py 的返回对应）。纯类型，区块组件可以直接 import。
 */

export interface ConversationRow {
  id: number;
  name: string;
  channel: "web" | "wecom";
  source: string;
  status: string;
  status_label: string;
  last_text: string;
  last_from: string;
  last_at: string;
  pending: number;
  failed: number;
  needs: number;
  takeover: boolean;
}

export interface AdminFile {
  id: number;
  name: string;
  size: number;
  purpose: string;
  note: string;
  role: string;
  round: number;
  url: string;
  is_image: boolean;
}

export interface AdminMessage {
  id: number;
  direction: "in" | "out";
  sender: "customer" | "bot" | "edison" | "system";
  kind: string;
  text: string;
  /** 固定内容：terms 交付和注意事项、payment 付款方式、owner_qr 负责人微信二维码、pay_qr 付款二维码 */
  card: string | null;
  file: AdminFile | null;
  image_url: string | null;
  created_at: string;
}

export interface ToolCall {
  name: string;
  args: Record<string, unknown>;
  result: string;
  summary: string;
}

export interface RunBrief {
  id: number;
  model: string;
  tools: ToolCall[];
  error: string;
  requests: number;
  input_tokens: number;
  output_tokens: number;
  started_at: string;
}

export interface OutboxItem {
  id: number;
  status: "pending" | "approved" | "failed" | "sent" | "rejected";
  status_label: string;
  kind: string;
  asset: string;
  text: string;
  original_text: string;
  category: string;
  author: "bot" | "edison" | "system";
  auto: boolean;
  reasons: string[];
  error: string;
  created_at: string;
  run: RunBrief | null;
}

export interface SendWindow {
  limited: boolean;
  can_send: boolean;
  sends_left: number | null;
  hours_left: number | null;
}

export interface Condition {
  key: string;
  name: string;
  ok: boolean;
  detail: string;
}

export interface Need {
  type: string;
  detail: string;
  at: string;
  resolved: boolean;
}

export interface RevisionItem {
  id: number;
  text: string;
  /** 逐页：page 空 = 整体意见 */
  items: { page: number | null; text: string }[];
  free: boolean;
  status: string;
  created_at: string;
  files: AdminFile[];
}

/** 一次开工交接：direct = 直接写进了工厂 inbox；pull = 交接包在平台里，等 Mac 来领（待领 → 已领） */
export interface HandoffInfo {
  id: number | null;
  mode: "direct" | "pull";
  status: "direct" | "ready" | "claimed";
  status_label: string;
  folder: string;
  files: string[];
  size: number;
  created_at: string;
  claimed_at: string | null;
  claimed_folder: string;
}

/** 制作方会话的一条：to_maker 业务员（助手）写给制作方；to_sales 制作方写给业务员 */
export interface ProductionItem {
  id: number;
  direction: "to_maker" | "to_sales";
  kind: string;
  author: "bot" | "system" | "maker" | "edison";
  text: string;
  files: AdminFile[];
  read_at: string | null;
  relayed_at: string | null;
  created_at: string;
}

/** 流程里后台能手动推的一条连线（流程文件里标了 manual 的） */
export interface ManualEdge {
  on: string;
  to: string;
  stage: string;
  stage_label: string;
  label: string;
}

export interface OrderAddon {
  key: string;
  name: string;
  /** bundle 同一笔买的 / code 单独的加购码 / edison 后台给的 */
  by: string;
  code: string;
}

export interface OrderDetail {
  id: number;
  status: string;
  status_label: string;
  /** 订单状态（流程步骤标的）：paid / claimed / collecting / making / watermarked / revising / completed / delivered / void */
  stage: string;
  flow_key: string;
  flow_step: string;
  /** 这个流程的状态顺序（画进度条用，不含作废） */
  stage_track: { key: string; label: string }[];
  /** 细一层的进度（只读，给人看） */
  progress: string;
  manual: ManualEdge[];
  can_void: boolean;
  can_return_code: boolean;
  voided_from: string;
  voided_from_label: string;
  void_reason: string;
  hold_reason: string;
  platform: string;
  platform_order_id: string;
  buyer_id: string;
  source: string;
  paid_at: string | null;
  paid_amount: string;
  claimed_at: string | null;
  platform_completed_at: string | null;
  completed_at: string | null;
  sku: string;
  sku_name: string;
  addons: OrderAddon[];
  max_pages: number | null;
  due_hours: number | null;
  page_rule: string;
  occasion: string;
  title: string;
  duration_min: number | null;
  duration_default: boolean;
  duration_confirmed: boolean;
  paper_count: number | null;
  page_count: number | null;
  present_date: string | null;
  present_date_text: string;
  school: string;
  language: string;
  structure_req: string;
  requirement_quotes: string[];
  quoted_price: string;
  tier_key: string;
  tier_name: string;
  code: string;
  redeemed_at: string | null;
  revisions_left: number;
  extra_revisions: number;
  rush: boolean;
  rush_by_edison: boolean;
  needs: Need[];
  required: { purpose: string; ok: boolean }[];
  optional_hint: string;
  materials: AdminFile[];
  conditions: Condition[];
  plan: { start_date: string; eta_date: string } | null;
  queued: boolean;
  start_date: string | null;
  eta_date: string | null;
  started_at: string | null;
  handoff_folder: string;
  handoff: HandoffInfo | null;
  handoff_mode: "direct" | "pull";
  deliverables: AdminFile[];
  /** 这一版还没交的整页图张数 */
  pages: number;
  delivery_round: number;
  delivered_at: string | null;
  /** 不加急的单第一版做好了、压着：几点自动发给客人（没压着就是 null） */
  hold_until?: string | null;
  has_new_deliverable: boolean;
  can_submit_package: boolean;
  revisions: RevisionItem[];
  received_at: string | null;
  feedback: Record<string, unknown> | null;
  finished_at: string | null;
  delivery_url: string;
  /** 制作方那边：待开 / 在做 / 做好了 / 交了水印版……；没开工是空 */
  maker_state: string;
  production: ProductionItem[];
  created_at: string;
}

export interface ConversationDetail {
  customer: {
    id: number;
    name: string;
    nickname: string;
    channel: "web" | "wecom";
    source: string;
    takeover: boolean;
    note: string;
    created_at: string;
  };
  window: SendWindow;
  messages: AdminMessage[];
  outbox: OutboxItem[];
  order: OrderDetail | null;
  last_run: RunBrief | null;
  bot_ready: boolean;
  /** 手动开单能选的基础货号 */
  base_skus: { sku: string; name: string; price: string }[];
}

export interface OrderRow {
  id: number;
  /** 平台付了款、还没人认领的单没有会话 */
  customer_id: number | null;
  name: string;
  channel: "web" | "wecom" | "";
  platform: string;
  status: string;
  status_label: string;
  stage: string;
  progress: string;
  occasion: string;
  duration_min: number | null;
  present_date: string | null;
  eta_date: string | null;
  start_date: string | null;
  due_hours: number | null;
  quoted_price: string;
  rush: boolean;
  redeemed: boolean;
  sku_name: string;
  tier_name: string;
  maker_state: string;
  hold_reason: string;
  needs: number;
  pending: number;
  has_new_deliverable: boolean;
  updated_at: string;
}

/** 资料清单的一样（对客人说的字）：东西 + 半句用来干什么；必须发的要写 purpose（登记成哪种用途，代码按它核对齐没齐）；
 * 每个场合都要说的写 key（对上资料清单里的一项：duration_min / present_date / school） */
export interface MaterialLine {
  text: string;
  use: string;
  purpose: string;
  key: string;
}

export interface OccasionRule {
  /** 对客叫法（组会读文献）；空就用场合名 */
  name: string;
  /** 必须发的（required 由它算，后端存的时候重算） */
  must: MaterialLine[];
  /** 有的话更好的 */
  nice: MaterialLine[];
  required: string[];
  /** 给模型看的登记说明 */
  optional_hint: string;
  default_minutes: number;
}

/** 资料清单对客的几句（官网、下单页、小鱼、认领那句话、场合定了那条都从这里出）；{name} = 场合的对客叫法 */
export interface MaterialsGuideSettings {
  site_title: string;
  site_lead: string;
  order_head: string;
  visitor_head: string;
  overview_head: string;
  overview_tail: string;
  must_title: string;
  nice_title: string;
  common_title: string;
  received_mark: string;
  start_rule: string;
  other_text: string;
  common: MaterialLine[];
  find_refs_line: MaterialLine | null;
  order: string[];
}

/** 一个时长档：汇报时长上限、页数上限（内容页）、各篇数档的价、标准 / 加急时限 */
export interface DurationTier {
  key: string;
  name: string;
  max_minutes: number;
  max_pages: number;
  /** 篇数档 key → 价；空 = 不开放 */
  prices: Record<string, string>;
  std_hours: number;
  rush_hours: number;
  rush: boolean;
  /** 以后压到（只是备注，不参与报价） */
  later_price: string;
}

export interface PaperBand {
  key: string;
  name: string;
  max_papers: number;
}

export interface Addon {
  key: "rush" | "revision" | "find_refs";
  name: string;
  price: string;
  note: string;
}

export interface DeliverySettings {
  remind_before_hours: number;
  revision_hours: number;
  confirm_sources_by_platform: Record<string, string[]>;
  texts: Record<string, string>;
  /** 水印浓淡（水印字不透明度），Edison 看样张定，先用 0.20 */
  watermark_alpha: number;
}

export interface PaymentChannel {
  text: string;
  link: string;
  qr_image: string;
}

export interface BizConfig {
  schema_version: number;
  occasions: Record<string, OccasionRule>;
  daily_quota: number;
  buffer_days: number;
  queue_horizon_days: number;
  duration_tiers: DurationTier[];
  paper_bands: PaperBand[];
  addons: Addon[];
  find_refs_extra_hours: number;
  /** 对客承诺比正常用时多说几小时（默认 2） */
  promise_buffer_hours: number;
  page_rule_text: string;
  rush_daily_quota: number;
  work_start_hour: number;
  visitor_daily_limit: number;
  visitor_global_daily_limit: number;
  refund_block_after: number;
  revise_after_days: number;
  auto_confirm_days: number;
  delivery: DeliverySettings;
  checklists: Record<string, unknown>;
  materials: MaterialsGuideSettings;
  entry_texts: Record<string, string>;
  delivery_templates: Record<string, string>;
  deliver_text: string;
  notes_text: string;
  payment: PaymentChannel;
  revisions_included: number;
  /** 哪几类回复先给后台看再发（默认都不批） */
  approval: Record<string, boolean>;
  welcome_text: string;
  faq: { q: string; a: string }[];
}

export interface AdminSettings {
  config: BizConfig;
  categories: string[];
  purposes: string[];
  deliverable_kinds: string[];
  images: { pay_qr: boolean; owner_qr: boolean; service_qr: boolean };
  payment_ready: boolean;
  price_hash: string;
  production_token: boolean;
  wecom: {
    corpid: boolean;
    secret: boolean;
    token: boolean;
    aes_key: boolean;
    open_kfid: boolean;
    callback_path: string;
  };
  model: { configured: boolean; name: string };
  factory_inbox: string;
  handoff_mode: "direct" | "pull";
  factory_pull_token: boolean;
}

export interface FactoryJob {
  job: string;
  files: { name: string; size: number }[];
}

/** 订单字段改动（后台订单卡「保存」时发） */
export interface OrderPatch {
  occasion?: string;
  title?: string;
  duration_min?: number;
  clear_duration?: boolean;
  duration_confirmed?: boolean;
  present_date?: string;
  clear_present_date?: boolean;
  school?: string;
  language?: string;
  structure_req?: string;
  requirement_quotes?: string[];
  paper_count?: number;
  page_count?: number;
}

export const CHANNEL_LABEL: Record<string, string> = { web: "网页聊天", wecom: "微信客服" };

// ---------------- 激活码 ----------------

export interface CodeRow {
  id: number;
  code: string;
  sku: string;
  addons: string[];
  sku_name: string;
  platform: string;
  platform_order_id: string;
  status: "unused" | "used" | "void";
  status_label: string;
  batch: string;
  note: string;
  expires_at: string | null;
  order_id: number | null;
  customer_id: number | null;
  customer_name: string;
  used_at: string | null;
  voided_at: string | null;
  created_at: string;
}

export interface CodeBatch {
  batch: string;
  sku: string;
  sku_name: string;
  count: number;
  created_at: string;
}

export interface CodeList {
  rows: CodeRow[];
  counts: { unused: number; used: number; void: number };
  skus: { sku: string; name: string; price: string; kind: "base" | "addon" }[];
  batches: CodeBatch[];
}

export interface CodeGenerateIn {
  sku: string;
  count: number;
  note: string;
  expires_on: string | null;
  platform?: string;
  addons?: string[];
}

// ---------------- 节点目录（/api/admin/nodes） ----------------

export interface NodeField {
  name: string;
  type: string;
  required: boolean;
  description: string;
}

export interface NodeCardInfo {
  id: string;
  name: string;
  description: string;
  category: string;
  tech: string[];
  input: { model: string; fields: NodeField[] };
  output: { model: string; fields: NodeField[] };
  exits: { key: string; label: string; kind: "ok" | "fail" | "wait" }[];
  config: string[];
  emits: string[];
  listens: string[];
  replaceable: string[];
  failure: string;
  owner: string;
  status: string;
  runnable: boolean;
  /** 哪些流程用到它 */
  flows: string[];
}

export interface FlowStep {
  id: string;
  stage: string;
  stage_label: string;
  node: string;
  enter: string | null;
  label: string;
  terminal: boolean;
  edges: { on: string; to: string; manual: boolean; loop: boolean; label: string; when: Record<string, unknown>[] }[];
}

export interface FlowInfo {
  key: string;
  subject: string;
  name: string;
  description: string;
  start: string;
  stages: { key: string; label: string }[];
  steps: FlowStep[];
}

export interface NodeCatalog {
  categories: string[];
  nodes: NodeCardInfo[];
  flows: FlowInfo[];
}
