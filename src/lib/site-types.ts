/** 统一站点地图和聚人这条线的类型（后端 /api/gather/*，模块 L）。 */

export type SiteSection = "main" | "app" | "figures";

export interface SiteLink {
  label: string;
  href: string;
  section?: SiteSection;
}

export interface SiteGroup {
  key: string;
  title: string;
  items: SiteLink[];
}

export interface SiteBrand {
  name: string;
  href: string;
}

export interface SiteMap {
  bases: Record<SiteSection, string>;
  brands: { ppt: SiteBrand; figures: SiteBrand };
  groups: SiteGroup[];
  company: string;
  credit_code: string;
  icp: string;
  icp_url: string;
  cta: { text: string; site_url: string; order_url: string };
  unlock_enabled: boolean;
  verifier: "screenshot_trust" | "follow_gzh" | "share_visits" | "manual";
  plugin_name: string;
  gzh_name: string;
  gzh_keyword: string;
  follow_note: string;
  library_version: string;
  takedown_hours: number;
}

export interface UnlockView {
  share_code: string;
  share_text: string;
  stage: "requested" | "checking" | "passed" | "sent" | string;
  stage_label: string;
  verifier: SiteMap["verifier"];
  reason: string;
  share_visits: number;
  need_visits: number;
  /** 只有「已发链接」才有；没核验过永远是空的 */
  pack_text: string;
  pack_version: string;
  follow_note: string;
  gzh_name: string;
  gzh_keyword: string;
}

export type CtaPlacement = "header" | "nav" | "home" | "results" | "detail" | "unlock_done" | "footer" | "plugin";
export type CtaTarget = "order" | "site" | "gzh";

export interface TakedownDraft {
  figures: string;
  holder: string;
  contact: string;
  reason: string;
  website: string;
}

/* ---- 后台 ---- */
export interface GatherOverview {
  days: number;
  visits: number;
  visits_by_src: { src: string; n: number }[];
  share_new_visitors: number;
  unlock_requested: number;
  unlock_evidence: number;
  unlock_sent: number;
  top_sharers: { share_code: string; visits: number; stage: string }[];
  cta_clicks: { what: string; n: number }[];
  search_by_caller: Record<string, number>;
  orders_from_tuku: number;
  grants: number;
}

export interface AdminUnlock {
  id: number;
  created_at: string;
  share_code: string;
  visitor: string;
  src: string;
  stage: string;
  stage_label: string;
  flow_step: string;
  verifier: string;
  reason: string;
  share_visits: number;
  evidence: { id: number; url: string; mark: string; created_at: string }[];
  sent_at: string | null;
  resend_count: number;
  actions: { on: string; label: string }[];
}

export interface AdminPack {
  id: number;
  version: string;
  tier: "full" | "lite";
  provider: string;
  url: string;
  extract_code: string;
  count: number;
  size_mb: number;
  active: boolean;
  note: string;
  updated_at: string;
  grants: number;
}

export interface PackDraft {
  version: string;
  tier: "full" | "lite";
  url: string;
  extract_code: string;
  count: number;
  note: string;
}

export interface GatherConfig {
  values: Record<string, string | number | boolean>;
  labels: Record<string, string>;
  verifiers: Record<string, string>;
}

export interface AdminTakedown {
  id: number;
  created_at: string;
  deadline_at: string | null;
  overdue: boolean;
  hours_left: number | null;
  figure_ids: number[];
  figures: { id: number; thumb_url: string; title: string }[];
  figures_text: string;
  holder: string;
  contact: string;
  reason: string;
  decision: string;
  admin_note: string;
}
