import type { ReactNode } from "react";

import { fmtMs, fmtTime, type OpsAlert, type OpsErrorRow, type SlowRow } from "@/lib/ops-types";
import { cn } from "@/lib/utils";

export interface OpsErrorsProps {
  alerts: OpsAlert[];
  errors: OpsErrorRow[];
  slow: SlowRow[];
  /** 手动关掉一条告警（问题处理好了，不想等它自己恢复） */
  onResolve: (alert: OpsAlert) => void;
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

/** 前端兜底路由（整页 HTML）换成人话 */
const routeLabel = (r: string) => (r === "/{full_path:path}" ? "网页整页（前端页面）" : r);

const empty = (text: string) => <p className="rounded-lg border px-4 py-4 text-sm text-muted-foreground">{text}</p>;

/** 错误与告警：告警（开着的在前，带级别、影响什么、推过几次）、最近的 5xx（请求号能在日志里查）、慢接口。只吃 props。 */
export function OpsErrors({ alerts, errors, slow, onResolve }: OpsErrorsProps) {
  const open = alerts.filter((a) => a.status === "open");
  const closed = alerts.filter((a) => a.status !== "open").slice(0, 10);
  return (
    <div className="flex flex-col gap-6" data-testid="ops-errors">
      <Section title="告警" note="同一个问题只算一条；推过之后静默一段时间不重复推">
        {open.length || closed.length ? (
          <ul className="divide-y rounded-lg border">
            {[...open, ...closed].map((a) => (
              <li key={a.id} className="flex flex-wrap items-start gap-x-4 gap-y-1 px-4 py-3">
                <span
                  className={cn(
                    "mt-0.5 w-24 shrink-0 text-xs",
                    a.status !== "open" ? "text-muted-foreground" : a.level === "urgent" ? "font-medium text-destructive" : "font-medium text-foreground",
                  )}
                >
                  {a.status === "open" ? a.level_label : "已恢复"}
                </span>
                <div className="flex min-w-0 flex-1 flex-col gap-0.5">
                  <span className={cn("text-sm", a.status === "open" ? "text-foreground" : "text-body")}>{a.title}：{a.detail}</span>
                  <span className="text-xs text-muted-foreground">
                    影响：{a.impact} · {fmtTime(a.first_at)} 开始
                    {a.count > 1 ? ` · 又触发 ${a.count - 1} 次` : ""}
                    {a.notify_count ? ` · 推过 ${a.notify_count} 次` : " · 没推"}
                    {a.resolved_at ? ` · ${fmtTime(a.resolved_at)} ${a.resolved_by === "edison" ? "手动关掉" : "自己恢复"}` : ""}
                  </span>
                </div>
                {a.status === "open" ? (
                  <button type="button" className="shrink-0 rounded-md border px-3 py-1 text-xs text-body hover:bg-accent" onClick={() => onResolve(a)}>
                    处理好了，关掉
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        ) : (
          empty("没有告警。")
        )}
      </Section>

      <Section title="最近的错误（5xx）" note="请求号可以拿去日志里搜，同一次请求的每一行都带它；网址里的令牌不记">
        {errors.length ? (
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[40rem] text-sm">
              <thead className="border-b bg-card text-left text-xs text-muted-foreground">
                <tr>
                  <th className="px-4 py-2 font-normal">时间</th>
                  <th className="px-2 py-2 font-normal">接口</th>
                  <th className="px-2 py-2 font-normal">状态</th>
                  <th className="px-2 py-2 font-normal">类型和摘要</th>
                  <th className="px-4 py-2 font-normal">请求号</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {errors.map((e) => (
                  <tr key={e.id} className="align-top">
                    <td className="px-4 py-2 whitespace-nowrap text-body tabular-nums">{fmtTime(e.at)}</td>
                    <td className="px-2 py-2 break-all text-foreground">
                      {e.method} {routeLabel(e.route)}
                    </td>
                    <td className="px-2 py-2 text-destructive tabular-nums">{e.status}</td>
                    <td className="px-2 py-2 text-xs text-body">
                      {e.kind}
                      {e.message ? `：${e.message}` : ""}
                    </td>
                    <td className="px-4 py-2 font-mono text-xs text-muted-foreground">{e.rid}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          empty("最近没有 5xx 错误。")
        )}
      </Section>

      <Section title="慢接口（近 7 天）" note="按 95% 请求的用时从慢到快；至少 5 次才列；后台、健康检查、静态文件不算">
        {slow.length ? (
          <div className="overflow-x-auto rounded-lg border">
            <table className="w-full min-w-[36rem] text-sm">
              <thead className="border-b bg-card text-left text-xs text-muted-foreground">
                <tr>
                  <th className="px-4 py-2 font-normal">接口</th>
                  <th className="px-2 py-2 text-right font-normal">次数</th>
                  <th className="px-2 py-2 text-right font-normal">一半在</th>
                  <th className="px-2 py-2 text-right font-normal">95% 在</th>
                  <th className="px-4 py-2 text-right font-normal">出错</th>
                </tr>
              </thead>
              <tbody className="divide-y">
                {slow.map((r) => (
                  <tr key={`${r.method} ${r.route}`}>
                    <td className="px-4 py-2 break-all text-foreground">
                      {r.method} {routeLabel(r.route)}
                    </td>
                    <td className="px-2 py-2 text-right text-body tabular-nums">{r.n.toLocaleString("zh-CN")}</td>
                    <td className="px-2 py-2 text-right text-body tabular-nums">{fmtMs(r.p50_ms)}</td>
                    <td className={cn("px-2 py-2 text-right tabular-nums", (r.p95_ms ?? 0) >= 2000 ? "font-medium text-destructive" : "text-foreground")}>
                      {fmtMs(r.p95_ms)}
                    </td>
                    <td className={cn("px-4 py-2 text-right tabular-nums", r.errors_5xx ? "text-destructive" : "text-muted-foreground")}>{r.errors_5xx}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          empty("还没有数据（计数每分钟写一次库）。")
        )}
      </Section>
    </div>
  );
}
