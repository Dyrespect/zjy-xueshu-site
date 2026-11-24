import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { fmtBytes, fmtTime, type OpsBackups as Data } from "@/lib/ops-types";
import { cn } from "@/lib/utils";

export interface OpsBackupsProps {
  data: Data;
  /** 正在跑哪一个：run / drill / "" */
  busy: string;
  onRun: () => void;
  onDrill: () => void;
}

const WEEKDAY = "一二三四五六日";

/** 备份：引擎和仓库在哪、最近一次成功 / 失败、最近一次恢复演练（核对数一项一项对）、备份列表、现在备份 / 现在演练。只吃 props。 */
export function OpsBackups({ data, busy, onRun, onDrill }: OpsBackupsProps) {
  const c = data.config;
  const drill = data.last_drill;
  const failedLater = data.last_failed && (!data.last_done || data.last_failed.at > data.last_done.at);
  return (
    <div className="flex flex-col gap-6" data-testid="ops-backups">
      <div className="flex flex-col gap-1 rounded-lg border px-4 py-3 text-sm">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="text-foreground">
            引擎：{data.engine === "restic" ? "restic（数据库快照 + 客户文件，加密、去重）" : "内置兜底（只有数据库、只在本机）"}
          </span>
          <div className="flex gap-2">
            <Button size="sm" onClick={onRun} disabled={!!busy}>
              {busy === "run" ? <Loader2 className="animate-spin" /> : null}
              现在备份
            </Button>
            <Button size="sm" variant="outline" onClick={onDrill} disabled={!!busy}>
              {busy === "drill" ? <Loader2 className="animate-spin" /> : null}
              现在做恢复演练
            </Button>
          </div>
        </div>
        <span className="text-xs text-muted-foreground">
          放在：{data.where}；每天 {c.time} 备份，留最近 {c.keep_daily} 天每天一份、{c.keep_weekly} 周每周一份（周{WEEKDAY[c.weekly_weekday]}那份），每{" "}
          {c.drill_every_days} 天做一次恢复演练。推对象存储：{data.cos_enabled ? "开着" : "关着（等 Edison 点头、把密钥存进文件）"}。
        </span>
        {data.engine !== "restic" ? (
          <span className="text-xs text-muted-foreground">
            {data.restic_installed ? "restic 装了，但还没给仓库密码文件（OPS_RESTIC_PASSWORD_FILE）。" : "restic 还没装（要 Edison 点头装）。"}
            装上之前客户文件没有备份；数据库每天照样在本机备一份。见 docs/运维/运维手册.md 第四节。
          </span>
        ) : null}
        {data.error ? <span className="text-xs text-destructive">{data.error}</span> : null}
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <section className="flex flex-col gap-2">
          <h2 className="text-sm font-medium text-foreground">最近一次备份</h2>
          <div className={cn("rounded-lg border px-4 py-3 text-sm", failedLater ? "border-destructive" : "")}>
            {data.last_done ? (
              <p className="text-body">
                {fmtTime(data.last_done.at)} 成功：{String(data.last_done.name ?? "")}，数据库 {fmtBytes(Number(data.last_done.db_bytes ?? 0))}
                {Number(data.last_done.files_count ?? 0) ? `，文件 ${Number(data.last_done.files_count)} 个` : ""}，用了 {String(data.last_done.seconds ?? "")} 秒
              </p>
            ) : (
              <p className="text-muted-foreground">还没备份过。</p>
            )}
            {failedLater && data.last_failed ? (
              <p className="mt-1 text-destructive">
                {fmtTime(data.last_failed.at)} 失败：{String(data.last_failed.error ?? "")}
              </p>
            ) : null}
          </div>
        </section>
        <section className="flex flex-col gap-2">
          <h2 className="text-sm font-medium text-foreground">最近一次恢复演练</h2>
          <div className={cn("rounded-lg border px-4 py-3 text-sm", drill && !drill.ok ? "border-destructive" : "")}>
            {drill ? (
              <>
                <p className={drill.ok ? "text-body" : "font-medium text-destructive"}>
                  {fmtTime(drill.at)} {drill.ok ? "恢复出来都对得上" : `没过：${drill.error || "核对数对不上"}`}（{drill.backup}，完整性 {drill.integrity || "—"}）
                </p>
                {drill.checks?.length ? (
                  <ul className="mt-2 flex flex-col gap-0.5 text-xs">
                    {drill.checks.map((x) => (
                      <li key={x.key} className={x.ok ? "text-muted-foreground" : "text-destructive"}>
                        {x.label}：备份时 {String(x.expected ?? "—")}，恢复后 {String(x.actual ?? "—")}
                        {x.ok ? "" : "（对不上）"}
                      </li>
                    ))}
                  </ul>
                ) : null}
              </>
            ) : (
              <p className="text-muted-foreground">还没演练过。</p>
            )}
          </div>
        </section>
      </div>

      <section className="flex flex-col gap-2">
        <h2 className="text-sm font-medium text-foreground">备份列表</h2>
        {data.engine === "restic" ? (
          data.restic.length ? (
            <ul className="divide-y rounded-lg border">
              {data.restic.map((s) => (
                <li key={s.id} className="flex justify-between gap-3 px-4 py-2 text-sm">
                  <span className="font-mono text-xs text-body">{s.id}</span>
                  <span className="text-body tabular-nums">{fmtTime(s.time)}</span>
                </li>
              ))}
            </ul>
          ) : (
            <p className="rounded-lg border px-4 py-4 text-sm text-muted-foreground">仓库里还没有快照。</p>
          )
        ) : data.builtin.length ? (
          <ul className="divide-y rounded-lg border">
            {data.builtin.map((b) => (
              <li key={b.name} className="grid grid-cols-[minmax(0,1fr)_5rem] gap-3 px-4 py-2 text-sm sm:grid-cols-[minmax(0,1fr)_6rem_6rem_minmax(0,14rem)]">
                <span className="break-all text-foreground">
                  {b.name}
                  {b.weekly ? <span className="ml-2 text-xs text-muted-foreground">周备</span> : null}
                </span>
                <span className="text-right text-body tabular-nums">{fmtBytes(b.bytes)}</span>
                <span className="hidden text-right text-body tabular-nums sm:block">{String(b.verify?.orders ?? "—")} 单</span>
                <span className="hidden text-right text-xs text-muted-foreground sm:block">实付合计 {String(b.verify?.paid_sum ?? "—")} 元</span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="rounded-lg border px-4 py-4 text-sm text-muted-foreground">还没有备份。</p>
        )}
      </section>
    </div>
  );
}
