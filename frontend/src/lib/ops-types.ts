/** 后台「运维」的数据类型（对着 backend/app/admin/ops_router.py）。 */

export type HealthStatus = "ok" | "warn" | "problem" | "skipped" | "off";
export type AlertLevel = "urgent" | "today" | "info";

export interface HealthItem {
  key: string;
  label: string;
  status: HealthStatus;
  detail: string;
  value: number | null;
}

export interface OpsHealth {
  ok: boolean;
  checked_at: string;
  items: HealthItem[];
}

export interface HttpSummary {
  requests: number;
  errors_5xx: number;
  errors_4xx: number;
  ratio_5xx: number | null;
  avg_ms: number | null;
  p50_ms: number | null;
  p95_ms: number | null;
  p99_ms: number | null;
}

export interface FunnelStep {
  key: string;
  label: string;
  count: number | null;
}

export interface ExternalRate {
  key: string;
  label: string;
  ok: number;
  fail: number;
  rate: number | null;
}

export interface OpsWindow {
  http: HttpSummary;
  pages: { pv: number; uv: number; by_page: Record<string, number> };
  funnel: FunnelStep[];
  payments: { checkouts: number; paid: number; success_rate: number | null; callback_invalid: number; paid_by_query: number };
  externals: ExternalRate[];
  capacity: { started: number };
  availability: { minutes: number; alive_minutes: number; ratio: number };
  refunds: number;
}

export interface OpsGauge {
  key: string;
  label: string;
  value: number | null;
  unit: string;
  detail: string;
  link: string;
}

export interface OpsAlert {
  id: number;
  key: string;
  rule: string;
  level: AlertLevel;
  level_label: string;
  title: string;
  detail: string;
  impact: string;
  link: string;
  status: "open" | "resolved";
  first_at: string;
  last_at: string;
  count: number;
  notified_at: string | null;
  notify_count: number;
  resolved_at: string | null;
  resolved_by: string;
}

export interface SenderStatus {
  sender: string;
  label: string;
  configured: boolean;
  source: string;
  signed: boolean;
  mode: string;
}

export interface JobState {
  id: string;
  label: string;
  last_at?: string;
  last_exit?: string;
  last_error?: string;
  seconds?: number;
}

export interface OpsOverviewData {
  now: string;
  timezone: string;
  windows: { today: OpsWindow; week: OpsWindow };
  gauges: OpsGauge[];
  gauge_errors: string[];
  alerts_open: OpsAlert[];
  backup: {
    done_at: string | null;
    done: Record<string, unknown>;
    failed_at: string | null;
    failed: Record<string, unknown>;
    engine: string;
  };
  sender: SenderStatus;
  jobs: JobState[];
  last_report: { day?: string; title?: string; sent?: boolean; at?: string; detail?: string };
}

export interface OpsErrorRow {
  id: number;
  at: string;
  rid: string;
  method: string;
  route: string;
  status: number;
  kind: string;
  message: string;
  ms: number;
}

export interface SlowRow {
  route: string;
  method: string;
  n: number;
  errors_5xx: number;
  avg_ms: number;
  p50_ms: number | null;
  p95_ms: number | null;
  max_ms: number;
}

export interface DrillCheck {
  key: string;
  label: string;
  expected: string | number | null;
  actual: string | number | null;
  ok: boolean;
}

export interface BuiltinBackup {
  name: string;
  created_at: string;
  local_date: string;
  weekly: boolean;
  db_bytes: number;
  bytes: number;
  verify: Record<string, string | number | null>;
}

export interface OpsBackups {
  engine: "restic" | "builtin";
  restic_installed: boolean;
  cos_enabled: boolean;
  where: string;
  builtin: BuiltinBackup[];
  restic: { id: string; time: string; paths: number }[];
  error: string;
  last_done: ({ at: string } & Record<string, unknown>) | null;
  last_failed: ({ at: string; error?: string } & Record<string, unknown>) | null;
  last_drill: ({ at: string; ok: boolean; backup: string; integrity: string; checks: DrillCheck[]; error: string } & Record<string, unknown>) | null;
  config: BackupConfig;
}

export interface MessageLine {
  text: string;
  link: string;
}

export interface OpsMessageView {
  title: string;
  level: AlertLevel;
  text: string;
  sections: { title: string; lines: MessageLine[] }[];
}

export interface ReportPreview {
  day: string;
  problems: number;
  message: OpsMessageView;
}

export interface Retention {
  raw_days: number;
  hourly_days: number;
  errors_days: number;
  visitors_days: number;
  alerts_days: number;
  notify_days: number;
}

export interface PushConfig {
  enabled: boolean;
  levels: AlertLevel[];
  silence_minutes: Record<AlertLevel, number>;
  max_per_hour: number;
  notify_resolved: boolean;
}

export interface RuleOverride {
  enabled: boolean;
  push: boolean;
  level: AlertLevel | null;
  params: Record<string, number>;
}

export interface ReportConfig {
  enabled: boolean;
  time: string;
  latest_n: number;
}

export interface BackupConfig {
  enabled: boolean;
  time: string;
  keep_daily: number;
  keep_weekly: number;
  weekly_weekday: number;
  drill_every_days: number;
  verify: { key: string; label: string; table: string; agg: string; column: string }[];
}

export interface LifeItem {
  key: string;
  label: string;
  days: number | null;
  how: string;
  confirm_by: string;
}

export interface OpsConfig {
  retention: Retention;
  push: PushConfig;
  rules: Record<string, RuleOverride>;
  report: ReportConfig;
  backup: BackupConfig;
  lifecycle: LifeItem[];
  lifecycle_confirmed: string[];
  thresholds_confirmed: boolean;
  funnel: { key: string; label: string; source: string }[];
  externals: { key: string; label: string; ok: string; fail: string }[];
}

export interface MergedRule {
  id: string;
  title: string;
  level: AlertLevel;
  link: string;
  impact: string;
  params: Record<string, number>;
  enabled: boolean;
  push: boolean;
}

export interface OpsSettingsData {
  config: OpsConfig;
  rules: MergedRule[];
  levels: Record<AlertLevel, string>;
  sender: SenderStatus;
  rule_defaults: Record<string, Record<string, number>>;
  backup_env: { engine: string; restic_installed: boolean; cos_enabled: boolean };
}

export interface LifecycleRow {
  key: string;
  label: string;
  days: number | null;
  expired: number | null;
  note: string;
}

export interface LifecycleScan {
  rows: LifecycleRow[];
  errors: string[];
  confirmed: string[];
}

/** 毫秒 → 「120 毫秒」「1.4 秒」 */
export function fmtMs(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return "—";
  return ms >= 1000 ? `${(ms / 1000).toFixed(1)} 秒` : `${Math.round(ms)} 毫秒`;
}

export function fmtPct(x: number | null | undefined, digits = 1): string {
  if (x === null || x === undefined) return "—";
  return `${(x * 100).toFixed(digits)}%`;
}

export function fmtNum(x: number | null | undefined): string {
  if (x === null || x === undefined) return "—";
  return x.toLocaleString("zh-CN");
}

export function fmtBytes(n: number | null | undefined): string {
  if (!n) return "—";
  if (n >= 1e9) return `${(n / 1e9).toFixed(1)} GB`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)} MB`;
  return `${Math.max(1, Math.round(n / 1e3))} KB`;
}

/** ISO 时间 → 北京时间「11-18 09:30」 */
export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export const STATUS_LABELS: Record<HealthStatus, string> = {
  ok: "正常",
  warn: "注意",
  problem: "有问题",
  skipped: "没配，跳过",
  off: "已关",
};

export const PARAM_LABELS: Record<string, string> = {
  window_minutes: "看最近几分钟",
  ratio: "出错比例到多少（0.05 = 5%）",
  min_errors: "至少错几次才算",
  min_count: "几条就报",
  window_hours: "看最近几小时",
  after_minutes: "付款后几分钟还没通知算缺",
  min_missing: "缺几笔就报",
  max_queue: "在排几版算积压",
  max_wait_minutes: "最老的等几分钟算积压",
  failed_hours: "几小时内出图失败要报",
  warn_pct: "用到百分之几提醒",
  urgent_pct: "用到百分之几立刻报",
  max_age_hours: "几小时没备份成功就报",
  warn_days: "还剩几天提醒",
  urgent_days: "还剩几天立刻报",
  fail_times: "连续连不上几次才报",
  every_minutes: "几分钟查一次外部服务",
};
