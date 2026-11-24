/**
 * 需求卡（09 需求引导）的数据类型。纯类型、不发请求，区块组件可以直接 import。
 * 字段照后端 app/intake/brief.py 的 view()、app/channels/brief_web.py、app/admin/brief_router.py。
 * 题目、选项、示例句、推荐值、样张、按钮上的字全从后端设置来，前端不写死（scripts/check.py 规矩 21）。
 */

export const DEFAULT_CHOICE = "__default__";
export const NONE_STYLE = "__none__";

export interface BriefOption {
  key: string;
  label: string;
  example: string;
  fact: string;
  upload: boolean;
}

export interface BriefQuestion {
  key: string;
  title: string;
  hint: string;
  kind: "single" | "multi" | "minutes";
  fact: "" | "occasion" | "language";
  optional: boolean;
  allow_note: boolean;
  note_placeholder: string;
  default: string | string[];
  options: BriefOption[];
}

export interface BriefSample {
  key: string;
  title: string;
  note: string;
  image: string;
  source: string;
}

export interface BriefStyle {
  title: string;
  hint: string;
  none_label: string;
  none_placeholder: string;
  default: string;
  default_text: string;
  samples: BriefSample[];
}

export interface BriefRefs {
  title: string;
  hint: string;
  max_files: number;
}

export interface BriefSettings {
  remind_after_hours: number;
  minutes_step: number;
  minutes_floor: number;
  questions: BriefQuestion[];
  style: BriefStyle;
  refs: BriefRefs;
  texts: Record<string, string>;
}

/** 一题的答案：choice 是选项 key（多选是 key 列表）、"__default__"（按推荐）、样张的 "__none__"（都不像） */
export interface BriefAnswer {
  choice: string | string[];
  note?: string;
}

export type BriefAnswers = Record<string, BriefAnswer>;

export interface BriefCardLine {
  key: string;
  label: string;
  value: string;
  by_default: boolean;
  missing: boolean;
}

export interface BriefFile {
  id: number;
  name: string;
  size: number;
  kind: "ref" | "template";
}

export interface BriefView {
  order_no: string;
  sku_name: string;
  tier_name: string;
  minutes: { low: number; high: number; options: number[]; default: number };
  settings: Pick<BriefSettings, "questions" | "style" | "refs" | "texts">;
  answers: BriefAnswers;
  version: number;
  files: BriefFile[];
  card: BriefCardLine[];
  missing: string[];
  /** open 在填；sent_back 负责人改了发回；confirmed 确认了；locked 已经开工、不能改 */
  state: "open" | "sent_back" | "confirmed" | "locked";
  editable: boolean;
  confirmed_at: string | null;
  confirm_method: "" | "customer" | "proxy";
  confirm_note: string;
  sent_back_note: string;
  stage: string;
  /** 客人页面才有：回聊天的地址（只给这单主人的浏览器）、确认以后接下来做什么 */
  chat_path?: string;
  next?: { text: string; where: string; chat_path: string };
  /** 还没勾过三项同意（平台单）：确认卡上要勾了才能点「对，开工」。旧后端没有这项 = 不用勾 */
  consent_needed?: boolean;
  /** 基础价含几轮修改（勾选里那句「不满意可以改几轮」） */
  revisions_included?: number;
}

export interface BriefHistoryItem {
  at: string;
  what: string;
  who: string;
  note: string;
}

/** 后台看的：多了地址、开工条件那一行、确认卡快照、改动记录 */
export interface BriefAdminView extends BriefView {
  order_id: number;
  url: string;
  condition: { ok: boolean; detail: string };
  card_text: string;
  confirmed_by: string;
  history: BriefHistoryItem[];
}
