/** 图库接口的数据结构（跟 backend/app/figures/schemas.py 对应）。只有类型，不发请求，区块组件可以直接用。 */

export interface TypeRef {
  code: string;
  name: string;
}

export interface TypeCount extends TypeRef {
  count: number;
}

export interface TypeGroup {
  key: string;
  title: string;
  types: TypeCount[];
}

export interface Chip {
  label: string;
  query: string;
}

export interface SiteInfo {
  service_url: string;
  qr_url: string;
  account_note: string;
  types: TypeRef[];
}

export interface HomeInfo {
  total: number;
  journals: number;
  groups: TypeGroup[];
  popular: Chip[];
}

export interface FigureCard {
  id: number;
  thumb_url: string;
  title: string;
  journal: string;
  year: string;
  tier: string;
  type_code: string;
  type_name: string;
}

export interface ResultGroup {
  key: string;
  title: string;
  learn: string;
  cards: FigureCard[];
}

export interface WordCount {
  word: string;
  count: number;
}

export interface SearchResult {
  search_id: number | null;
  query: string;
  words: WordCount[];
  zero_words: string[];
  guess: TypeRef | null;
  code: string;
  code_name: string;
  overridden: boolean;
  groups: ResultGroup[];
  total: number;
}

export interface BrowsePage {
  code: string;
  name: string;
  group_title: string;
  total: number;
  cards: FigureCard[];
}

export interface FigureTag {
  label: string;
  words: string[];
}

export interface FigureDetail extends FigureCard {
  preview_url: string;
  paper_title: string;
  authors: string;
  doi: string;
  link: string;
  caption: string;
  cite: string;
  types: TypeRef[];
  tags: FigureTag[];
  /** 「标签由 XX 改过」这类署名（审过的才有；模块 L） */
  credits?: string[];
}

/** 从搜索结果点进详情时带过去的上下文（反馈、提需求时一起交） */
export interface SearchContext {
  searchId: number | null;
  query: string;
}

export const FEEDBACK_REASONS: { value: string; label: string }[] = [
  { value: "wrong_type", label: "图型不对" },
  { value: "wrong_tags", label: "标签有错" },
  { value: "irrelevant", label: "和我搜的不相关" },
  { value: "unclear", label: "图不清楚" },
  { value: "other", label: "其他" },
];

export interface RequestDraft {
  want: string;
  method: string;
  contact: string;
  sketch: File | null;
  query: string;
  searchId: number | null;
  website: string;
}

export interface SubmissionDraft {
  image: File | null;
  source: string;
  reason: string;
  credit: string;
  website: string;
}

export interface Done {
  message: string;
}

/** 后台 */
export type InboxKind = "feedback" | "requests" | "submissions" | "site";

export interface InboxItem {
  id: number;
  created_at: string;
  status: "new" | "done";
  admin_note: string;
  handled_at: string | null;
  // feedback
  figure?: { id: number; thumb_url: string; title: string };
  reason?: string;
  note?: string;
  query?: string;
  // requests
  want?: string;
  method?: string;
  contact?: string;
  image_url?: string;
  // submissions
  source?: string;
  credit?: string;
  // 审核（模块 L：改标签、投图）
  proposed?: { what?: string; code?: string };
  decision?: "new" | "approved" | "rejected" | "hidden";
  // site
  content?: string;
  page?: string;
}

export interface InboxList {
  kind: InboxKind;
  counts: { new: number; done: number };
  items: InboxItem[];
}

export interface SearchStats {
  today: number;
  week: number;
  zero_words: { word: string; n: number }[];
  top_clicked: { id: number; thumb_url: string; title: string; n: number }[];
  recent: { id: number; created_at: string; query: string; code_name: string; total: number; zero_words: string[] }[];
}
