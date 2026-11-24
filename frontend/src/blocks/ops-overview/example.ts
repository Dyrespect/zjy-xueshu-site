import { defineBlockDemo } from "@/lib/blocks";
import type { OpsHealth, OpsOverviewData, OpsWindow } from "@/lib/ops-types";

import { OpsOverview } from "./OpsOverview";

// 下面的数是编的示意，不是真数据
function win(scale: number): OpsWindow {
  return {
    http: { requests: 1820 * scale, errors_5xx: 3 * scale, errors_4xx: 40 * scale, ratio_5xx: 0.0016, avg_ms: 48, p50_ms: 22, p95_ms: 180, p99_ms: 760 },
    pages: { pv: 260 * scale, uv: 96 * scale, by_page: { 图库: 180 * scale, 下单页: 50 * scale, 交付页: 30 * scale } },
    funnel: [
      { key: "visit", label: "访问（独立访客）", count: 96 * scale },
      { key: "checkout", label: "下单（自有网页）", count: 6 * scale },
      { key: "paid", label: "付款（全部渠道）", count: 5 * scale },
      { key: "claimed", label: "认领", count: 5 * scale },
      { key: "delivered", label: "交水印版", count: 4 * scale },
      { key: "completed", label: "确认收货", count: 3 * scale },
      { key: "invoice", label: "开票申请", count: 1 * scale },
    ],
    payments: { checkouts: 6 * scale, paid: 5 * scale, success_rate: 0.83, callback_invalid: 0, paid_by_query: 1 },
    externals: [
      { key: "deepseek", label: "DeepSeek（助手回消息）", ok: 120 * scale, fail: scale, rate: 0.992 },
      { key: "send", label: "给客人发消息（微信客服等）", ok: 300 * scale, fail: 0, rate: 1 },
      { key: "pay", label: "支付下单（网关）", ok: 6 * scale, fail: 0, rate: 1 },
      { key: "feishu", label: "飞书推送", ok: 2 * scale, fail: 0, rate: 1 },
    ],
    capacity: { started: 4 * scale },
    availability: { minutes: 600 * scale, alive_minutes: 600 * scale - scale, ratio: 0.9983 },
    refunds: scale - 1,
  };
}

export const SAMPLE_OVERVIEW: OpsOverviewData = {
  now: "2026-11-18T06:30:00Z",
  timezone: "Asia/Shanghai",
  windows: { today: win(1), week: win(7) },
  gauges: [
    { key: "watermark.rendering", label: "水印在排", value: 1, unit: "版", detail: "", link: "/admin/orders" },
    { key: "watermark.oldest_wait_min", label: "最老的等了", value: 2, unit: "分钟", detail: "", link: "/admin/orders" },
    { key: "watermark.failed_24h", label: "出图失败", value: 0, unit: "版", detail: "", link: "/admin/orders" },
    { key: "capacity.making", label: "在做", value: 3, unit: "单", detail: "", link: "/admin/orders" },
    { key: "capacity.waiting", label: "已认领、收资料中", value: 2, unit: "单", detail: "", link: "/admin/orders" },
    { key: "pay.notify_missing", label: "付款通知没到", value: 0, unit: "笔", detail: "", link: "/admin/channels" },
  ],
  gauge_errors: [],
  alerts_open: [],
  backup: { done_at: "2026-11-17T19:30:00Z", done: { name: "app-20261118-033000", engine: "builtin" }, failed_at: null, failed: {}, engine: "builtin" },
  sender: { sender: "feishu_webhook", label: "飞书群机器人", configured: true, source: "文件 /root/secrets/feishu_ops_webhook", signed: true, mode: "auto" },
  jobs: [
    { id: "flush", label: "计数落库", last_at: "2026-11-18T06:29:00Z", last_exit: "ok" },
    { id: "alerts", label: "告警检查", last_at: "2026-11-18T06:28:00Z", last_exit: "ok" },
    { id: "report", label: "每日汇报", last_at: "2026-11-18T01:00:00Z", last_exit: "sent" },
    { id: "backup", label: "备份", last_at: "2026-11-17T19:30:00Z", last_exit: "ok" },
  ],
  last_report: { day: "2026-11-17", title: "【日报】11-17（周二）网站一切正常", sent: true },
};

export const SAMPLE_HEALTH: OpsHealth = {
  ok: true,
  checked_at: "2026-11-18T06:30:00Z",
  items: [
    { key: "db_write", label: "数据库可写", status: "ok", detail: "写一行用了 4 毫秒", value: 4 },
    { key: "db_size", label: "数据库大小", status: "ok", detail: "库 18.2 MB，WAL 1.1 MB", value: 18.2 },
    { key: "watermark", label: "水印出图队列", status: "ok", detail: "在排 1 版，最老的等了 2 分钟", value: 1 },
    { key: "disk", label: "磁盘", status: "ok", detail: "用了 46%，还剩 21.4 GB（共 40 GB）", value: 46 },
    { key: "cert:psyppt.pilipala.zj.cn", label: "证书 psyppt.pilipala.zj.cn", status: "ok", detail: "还有 90 天到期", value: 90 },
    { key: "backup", label: "备份", status: "ok", detail: "最近一次成功是 11 小时前", value: 11 },
    { key: "ext:deepseek", label: "DeepSeek（助手）", status: "ok", detail: "通（HTTP 404）", value: null },
    { key: "ext:wechatpay", label: "微信支付", status: "skipped", detail: "没配，跳过", value: null },
  ],
};

export default defineBlockDemo({
  block: "ops-overview",
  title: "后台：运维总览",
  order: 95,
  component: OpsOverview,
  examples: [
    { name: "一切正常", props: { data: SAMPLE_OVERVIEW, health: SAMPLE_HEALTH } },
    {
      name: "有告警",
      props: {
        data: {
          ...SAMPLE_OVERVIEW,
          alerts_open: [
            {
              id: 3, key: "http_5xx", rule: "http_5xx", level: "urgent", level_label: "要立刻处理", title: "网站报错变多",
              detail: "近 10 分钟 400 次请求里 31 次出错（7.8%）", impact: "客人打开页面或提交时会看到「服务器出错了」", link: "/admin/ops?tab=errors",
              status: "open", first_at: "2026-11-18T06:20:00Z", last_at: "2026-11-18T06:28:00Z", count: 4, notified_at: "2026-11-18T06:20:00Z",
              notify_count: 1, resolved_at: null, resolved_by: "",
            },
          ],
        },
        health: { ...SAMPLE_HEALTH, ok: false, items: [...SAMPLE_HEALTH.items.slice(0, 3), { key: "disk", label: "磁盘", status: "problem", detail: "用了 91%，还剩 3.6 GB（共 40 GB）", value: 91 }] },
      },
    },
  ],
});
