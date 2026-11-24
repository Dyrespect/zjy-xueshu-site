import { defineBlockDemo } from "@/lib/blocks";
import type { OpsSettingsData } from "@/lib/ops-types";

import { OpsSettings } from "./OpsSettings";

// 默认设置的样子（和 backend/app/ops/config.py、alerts.json 的默认值一致）
const rule = (id: string, title: string, level: "urgent" | "today", link: string, params: Record<string, number>) => ({
  id, title, level, link, impact: "", params, enabled: true, push: true,
});
const rules = [
  rule("http_5xx", "网站报错变多", "urgent", "/admin/ops?tab=errors", { window_minutes: 10, ratio: 0.05, min_errors: 3 }),
  rule("db_unwritable", "数据库写不进去", "urgent", "/admin/ops", {}),
  rule("pay_notify_invalid", "支付回调验签失败", "urgent", "/admin/channels", { window_minutes: 60, min_count: 1 }),
  rule("pay_notify_silent", "支付通知很久没回来", "today", "/admin/channels", { after_minutes: 30, window_hours: 24, min_missing: 1 }),
  rule("watermark_backlog", "水印出图积压", "urgent", "/admin/ops", { max_queue: 5, max_wait_minutes: 15, failed_hours: 24 }),
  rule("disk_usage", "磁盘快满了", "today", "/admin/ops", { warn_pct: 80, urgent_pct: 90 }),
  rule("backup_failed", "备份失败或太久没备份", "urgent", "/admin/ops?tab=backups", { max_age_hours: 26 }),
  rule("cert_expiring", "网站证书快到期", "today", "/admin/ops", { warn_days: 14, urgent_days: 3 }),
  rule("external_down", "外部服务连不上", "today", "/admin/ops", { fail_times: 3, every_minutes: 10 }),
];

export const SAMPLE_SETTINGS: OpsSettingsData = {
  config: {
    retention: { raw_days: 30, hourly_days: 365, errors_days: 30, visitors_days: 2, alerts_days: 180, notify_days: 90 },
    push: { enabled: true, levels: ["urgent"], silence_minutes: { urgent: 60, today: 360, info: 1440 }, max_per_hour: 10, notify_resolved: true },
    rules: {},
    report: { enabled: true, time: "21:00", latest_n: 3 },
    backup: { enabled: true, time: "03:30", keep_daily: 7, keep_weekly: 4, weekly_weekday: 6, drill_every_days: 30, verify: [] },
    lifecycle: [
      { key: "materials", label: "客户材料（论文、开题报告、数据）", days: 90, how: "订单已交付满这么多天后删除文件，留文件名和大小（我的建议）", confirm_by: "法务" },
      { key: "watermark", label: "水印图、整页底图", days: 90, how: "订单已交付满这么多天后删除（我的建议）", confirm_by: "法务" },
      { key: "finals", label: "最终版（PPT、讲稿）", days: 180, how: "订单已交付满这么多天后删除，客人要再下载找负责人（我的建议）", confirm_by: "法务" },
      { key: "chat", label: "聊天记录", days: 365, how: "最后一条消息满这么多天后删正文、留条数（我的建议）", confirm_by: "法务" },
      { key: "invoices", label: "发票文件和开票信息", days: null, how: "待财务确认（不编数）", confirm_by: "财务" },
      { key: "payments", label: "付款记录、支付通知、退款记录", days: null, how: "待财务确认（不编数）", confirm_by: "财务" },
      { key: "events", label: "事件记录（平台申诉凭据）", days: null, how: "先一直留；要不要定期限待法务确认", confirm_by: "法务" },
    ],
    lifecycle_confirmed: [],
    thresholds_confirmed: false,
    funnel: [],
    externals: [],
  },
  rules,
  levels: { urgent: "要立刻处理", today: "今天看一下", info: "只是记录" },
  sender: { sender: "log", label: "没配（只写日志）", configured: false, source: "", signed: false, mode: "auto" },
  rule_defaults: Object.fromEntries(rules.map((r) => [r.id, r.params])),
  backup_env: { engine: "builtin", restic_installed: false, cos_enabled: false },
};

export default defineBlockDemo({
  block: "ops-settings",
  title: "后台：运维设置",
  order: 99,
  component: OpsSettings,
  examples: [
    {
      name: "默认值",
      props: {
        settings: SAMPLE_SETTINGS,
        lifecycle: { rows: [{ key: "materials", label: "", days: 90, expired: 12, note: "" }, { key: "chat", label: "", days: 365, expired: 0, note: "" }], errors: [], confirmed: [] },
        onSave: async () => undefined,
      },
    },
  ],
});
