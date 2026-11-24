/** 交付页的数据（和后端 app/delivery/router.py 的 DeliveryOut 一一对应）。模块 E。 */

export interface ProofPage {
  page: number;
  /** 一页水印图（长边 1920 的 JPEG） */
  url: string;
}

export interface ProofRound {
  round: number;
  published_at: string | null;
  pages: ProofPage[];
}

export interface RevisionState {
  can_submit: boolean;
  revisions_left: number;
  revision_used: number;
  /** 上一轮还在改 */
  open: boolean;
  page_count: number;
  based_on_round: number;
  whole_items_max: number;
  file_max_mb: number;
  /** 已交付后用剩下的那轮 */
  after_delivery: boolean;
  hint: string;
}

export interface ReceiptState {
  /** button 在这页点确认收货 | platform 去下单的平台点 | none 还不到时候 */
  mode: "button" | "platform" | "none";
  hint: string;
  platform_name: string;
  auto_confirm_at: string | null;
  auto_confirm_text: string;
  confirmed: boolean;
}

export interface FinalFile {
  id: number;
  name: string;
  kind: string;
  size: number;
  url: string;
}

export interface FinalState {
  released: boolean;
  /** 已完成了，最终版还在传 */
  waiting: boolean;
  files: FinalFile[];
}

export interface DeliveryData {
  order_no: string;
  occasion: string;
  title: string;
  duration_min: number | null;
  present_date: string | null;
  stage: string;
  status: string;
  step: number;
  steps: string[];
  queue_ahead: number | null;
  eta_date: string | null;
  due_text: string;
  cancelled: boolean;
  on_hold: boolean;
  delivered: boolean;
  latest_round: number;
  rounds: ProofRound[];
  revision: RevisionState;
  receipt: ReceiptState;
  final: FinalState;
  show_feedback: boolean;
  feedback_done: boolean;
}

/** 交付页上客人标的一条修改：page 空 = 整体意见；files 是附件（提交时变成下标） */
export interface RevisionDraft {
  key: string;
  page: number | null;
  text: string;
  files: File[];
}

export interface RevisionResult {
  ok: boolean;
  message: string;
  revision_id: number | null;
  free: boolean;
}

export interface ConfirmResult {
  ok: boolean;
  message: string;
  released: boolean;
  files: FinalFile[];
}

export type Satisfaction = "满意" | "一般" | "不满意";
