import type { ReactNode } from "react";

import {
  fmtMs,
  fmtNum,
  fmtPct,
  fmtTime,
  STATUS_LABELS,
  type HealthItem,
  type OpsHealth,
  type OpsOverviewData,
  type OpsWindow,
} from "@/lib/ops-types";
import { cn } from "@/lib/utils";

export interface OpsOverviewProps {
  data: OpsOverviewData;
  /** 深健康检查；还没查回来时给 null */
  health: OpsHealth | null;
  /** 点「告警」那一行时切到「错误与告警」 */
  onOpenAlerts?: () => void;
}

function Section({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-2">
      <div className="flex flex-wrap items-baseline gap-x-3">
        <h2 className="text-sm font-medium text-foreground">{title}</h2>
        {note ? <span className="text-xs text-muted-foreground">{note}</span> : null}
      </div>
      {children}
    </section>
  );
}

type Row = { label: string; today: string; week: string; bad?: boolean; note?: string };

function rows(t: OpsWindow, w: OpsWindow): Row[] {
  const funnel = (win: OpsWindow, key: string) => win.funnel.find((f) => f.key === key)?.count ?? null;
  return [
    { label: "可用性", today: fmtPct(t.availability.ratio, 2), week: fmtPct(w.availability.ratio, 2), note: "有心跳的分钟 / 全部分钟" },
    { label: "请求", today: fmtNum(t.http.requests), week: fmtNum(w.http.requests) },
    {
      label: "出错（5xx）",
      today: `${fmtNum(t.http.errors_5xx)}（${fmtPct(t.http.ratio_5xx)}）`,
      week: `${fmtNum(w.http.errors_5xx)}（${fmtPct(w.http.ratio_5xx)}）`,
      bad: (t.http.ratio_5xx ?? 0) >= 0.01,
    },
    { label: "一半请求在", today: fmtMs(t.http.p50_ms), week: fmtMs(w.http.p50_ms) },
    { label: "95% 请求在", today: fmtMs(t.http.p95_ms), week: fmtMs(w.http.p95_ms), bad: (t.http.p95_ms ?? 0) >= 2000 },
    { label: "访问（独立访客）", today: fmtNum(t.pages.uv), week: fmtNum(w.pages.uv), note: "7 天是按天去重后相加" },
    { label: "下单（自有网页）", today: fmtNum(funnel(t, "checkout")), week: fmtNum(funnel(w, "checkout")) },
    { label: "付款（全部渠道）", today: fmtNum(funnel(t, "paid")), week: fmtNum(funnel(w, "paid")) },
    { label: "支付成功率", today: fmtPct(t.payments.success_rate, 0), week: fmtPct(w.payments.success_rate, 0) },
    {
      label: "支付回调验签失败",
      today: fmtNum(t.payments.callback_invalid),
      week: fmtNum(w.payments.callback_invalid),
      bad: t.payments.callback_invalid > 0,
    },
    { label: "退款作废", today: fmtNum(t.refunds), week: fmtNum(w.refunds) },
    { label: "开工", today: `${t.capacity.started} 单`, week: `${w.capacity.started} 单` },
  ];
}

function HealthRow({ it }: { it: HealthItem }) {
  return (
    <li className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-x-3 gap-y-0.5 px-4 py-2.5 text-sm sm:grid-cols-[8rem_4.5rem_minmax(0,1fr)]">
      <span className="text-body">{it.label}</span>
      <span
        className={cn(
          "text-xs",
          it.status === "problem" ? "font-medium text-destructive" : it.status === "warn" ? "font-medium text-foreground" : "text-muted-foreground",
        )}
      >
        {STATUS_LABELS[it.status]}
      </span>
      <span className="col-span-2 min-w-0 text-xs break-words text-muted-foreground sm:col-span-1">{it.detail}</span>
    </li>
  );
}

/** 运维总览：关键数字（今天 / 近 7 天）、健康检查、漏斗、队列与做单、外部服务、定时任务。只吃 props。 */
export function OpsOverview({ data, health, onOpenAlerts }: OpsOverviewProps) {
  const t = data.windows.today;
  const w = data.windows.week;
  const alerts = data.alerts_open.filter((a) => a.level !== "info");
  // 告警开着的就不重复列健康检查里同一件事（磁盘、证书、备份、外部服务、数据库、水印都有对应的告警规则）
  const covered: Record<string, string> = { db_write: "db_unwritable", disk: "disk_usage", cert: "cert_expiring", backup: "backup_failed", ext: "external_down", watermark: "watermark_backlog" };
  const openRules = new Set(alerts.map((a) => a.rule));
  const healthProblems = (health?.items ?? []).filter((i) => i.status === "problem" && !openRules.has(covered[i.key.split(":")[0]] ?? ""));
  const todo = [...alerts.map((a) => `${a.title}（${a.level_label}）`), ...healthProblems.map((i) => `${i.label}：${i.detail}`)];
  return (
    <div className="flex flex-col gap-6" data-testid="ops-overview">
      <div className={cn("rounded-lg border px-4 py-3 text-sm", todo.length ? "border-destructive text-foreground" : "text-body")}>
        {todo.length ? (
          <button type="button" className="text-left" onClick={onOpenAlerts}>
            <span className="font-medium text-destructive">有 {todo.length} 件要处理：</span>
            {todo.slice(0, 4).join("；")}
          </button>
        ) : (
          <span>一切正常。没有开着的告警{health ? "，健康检查都过了" : ""}。</span>
        )}
      </div>

      <Section title="关键数字" note="今天 = 北京时间 0 点到现在；近 7 天 = 往前 7×24 小时">
        <div className="overflow-hidden rounded-lg border">
          <div className="grid grid-cols-[minmax(0,1fr)_5.5rem_5.5rem] gap-3 border-b bg-card px-4 py-2 text-xs text-muted-foreground sm:grid-cols-[minmax(0,1fr)_9rem_9rem]">
            <span>指标</span>
            <span className="text-right">今天</span>
            <span className="text-right">近 7 天</span>
          </div>
          <ul className="divide-y">
            {rows(t, w).map((r) => (
              <li key={r.label} className="grid grid-cols-[minmax(0,1fr)_5.5rem_5.5rem] items-baseline gap-3 px-4 py-2 text-sm sm:grid-cols-[minmax(0,1fr)_9rem_9rem]">
                <span className="min-w-0 text-body">
                  {r.label}
                  {r.note ? <span className="ml-2 hidden text-xs text-muted-foreground sm:inline">{r.note}</span> : null}
                </span>
                <span className={cn("text-right tabular-nums", r.bad ? "font-medium text-destructive" : "text-foreground")}>{r.today}</span>
                <span className="text-right text-body tabular-nums">{r.week}</span>
              </li>
            ))}
          </ul>
        </div>
      </Section>

      <Section title="健康检查" note={health ? `查于 ${fmtTime(health.checked_at)}` : "查询中…"}>
        {health ? (
          <ul className="divide-y rounded-lg border" data-testid="ops-health">
            {health.items.map((it) => (
              <HealthRow key={it.key} it={it} />
            ))}
          </ul>
        ) : (
          <p className="rounded-lg border px-4 py-3 text-sm text-muted-foreground">查询中…</p>
        )}
      </Section>

      <Section title="订单漏斗" note="下单只有自有网页才有；平台单付款时直接建单">
        <div className="flex flex-col gap-2 rounded-lg border px-4 py-3">
          {(["today", "week"] as const).map((k) => (
            <div key={k} className="flex flex-wrap items-baseline gap-x-1 gap-y-1 text-sm">
              <span className="w-14 shrink-0 text-xs text-muted-foreground">{k === "today" ? "今天" : "近 7 天"}</span>
              {data.windows[k].funnel.map((f, i) => (
                <span key={f.key} className="whitespace-nowrap text-body">
                  {i > 0 ? <span className="px-1 text-faint">›</span> : null}
                  {f.label.replace(/（.*?）/, "")} <span className="font-medium text-foreground tabular-nums">{fmtNum(f.count)}</span>
                </span>
              ))}
            </div>
          ))}
        </div>
      </Section>

      <div className="grid gap-6 lg:grid-cols-2">
        <Section title="队列与做单" note="每 5 分钟读一次">
          <ul className="divide-y rounded-lg border">
            {data.gauges.map((g) => (
              <li key={g.key} className="flex items-baseline justify-between gap-3 px-4 py-2 text-sm">
                <span className="text-body">{g.label}</span>
                <span className="text-foreground tabular-nums">
                  {g.value === null ? "—" : `${fmtNum(g.value)} ${g.unit}`}
                  {g.detail ? <span className="ml-2 text-xs text-muted-foreground">{g.detail}</span> : null}
                </span>
              </li>
            ))}
            {data.gauge_errors.map((e) => (
              <li key={e} className="px-4 py-2 text-xs text-muted-foreground">
                {e}
              </li>
            ))}
          </ul>
        </Section>
        <Section title="外部服务（近 7 天）" note="成功 / 失败次数">
          <ul className="divide-y rounded-lg border">
            {w.externals.map((x) => (
              <li key={x.key} className="flex items-baseline justify-between gap-3 px-4 py-2 text-sm">
                <span className="text-body">{x.label}</span>
                <span className={cn("tabular-nums", x.fail > 0 ? "font-medium text-foreground" : "text-body")}>
                  {x.rate === null ? "没调用过" : `${fmtPct(x.rate)}（失败 ${x.fail} / ${x.ok + x.fail}）`}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      </div>

      <Section title="定时任务" note={`推送：${data.sender.label}`}>
        <ul className="divide-y rounded-lg border">
          {data.jobs.map((j) => (
            <li key={j.id} className="grid grid-cols-[7rem_minmax(0,1fr)] gap-3 px-4 py-2 text-sm sm:grid-cols-[8rem_9rem_minmax(0,1fr)]">
              <span className="text-body">{j.label}</span>
              <span className="text-xs text-muted-foreground tabular-nums">{j.last_at ? `上次 ${fmtTime(j.last_at)}` : "还没跑过"}</span>
              <span className={cn("col-span-2 text-xs sm:col-span-1", j.last_exit === "fail" ? "font-medium text-destructive" : "text-muted-foreground")}>
                {j.last_exit ? `${j.last_exit}${j.last_error ? `：${j.last_error}` : ""}` : ""}
              </span>
            </li>
          ))}
        </ul>
      </Section>
    </div>
  );
}
