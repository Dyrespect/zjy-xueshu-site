import { Loader2 } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { PARAM_LABELS, type AlertLevel, type LifecycleScan, type OpsConfig, type OpsSettingsData } from "@/lib/ops-types";
import { cn } from "@/lib/utils";

export interface OpsSettingsProps {
  settings: OpsSettingsData;
  lifecycle: LifecycleScan | null;
  onSave: (config: Partial<OpsConfig>) => Promise<void>;
}

const inputCls = "h-9 rounded-md border border-input bg-background px-2.5 text-sm text-foreground outline-none focus-visible:border-ring";
const RETENTION: { key: keyof OpsConfig["retention"]; label: string }[] = [
  { key: "raw_days", label: "每分钟的原始计数" },
  { key: "hourly_days", label: "按小时合起来的计数" },
  { key: "errors_days", label: "最近错误" },
  { key: "visitors_days", label: "当天访客散列" },
  { key: "alerts_days", label: "关掉的告警" },
  { key: "notify_days", label: "业务通知记录（推了的、进日报的）" },
];

function Box({ title, note, children }: { title: string; note?: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-1">
      <div className="flex flex-wrap items-baseline gap-x-3">
        <h2 className="text-sm font-medium text-foreground">{title}</h2>
        {note ? <span className="text-xs text-muted-foreground">{note}</span> : null}
      </div>
      <div className="divide-y rounded-lg border">{children}</div>
    </section>
  );
}

function Num({ value, onChange, step, w = "w-24", placeholder }: {
  value: number | null;
  onChange: (v: number | null) => void;
  step?: number;
  w?: string;
  placeholder?: string;
}) {
  return (
    <input
      type="number"
      placeholder={placeholder}
      step={step ?? 1}
      className={cn(inputCls, w)}
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))}
    />
  );
}

/** 运维设置：告警阈值（每条规则开关、级别、几个数）、保留期、备份时间和保留份数、客户数据保存期限（待法务 / 财务确认）。只吃 props。 */
export function OpsSettings({ settings, lifecycle, onSave }: OpsSettingsProps) {
  const cfg = settings.config;
  const [rules, setRules] = useState(cfg.rules);
  const [retention, setRetention] = useState(cfg.retention);
  const [backup, setBackup] = useState(cfg.backup);
  const [life, setLife] = useState(cfg.lifecycle);
  const [confirmed, setConfirmed] = useState(cfg.lifecycle_confirmed);
  const [thresholdsOk, setThresholdsOk] = useState(cfg.thresholds_confirmed);
  const [busy, setBusy] = useState(false);
  const expired = Object.fromEntries((lifecycle?.rows ?? []).map((r) => [r.key, r.expired]));

  const rule = (id: string) => rules[id] ?? { enabled: true, push: true, level: null, params: {} };
  const setRule = (id: string, patch: Partial<OpsConfig["rules"][string]>) => setRules((r) => ({ ...r, [id]: { ...rule(id), ...patch } }));

  const save = async () => {
    setBusy(true);
    try {
      await onSave({ rules, retention, backup, lifecycle: life, lifecycle_confirmed: confirmed, thresholds_confirmed: thresholdsOk });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-6" data-testid="ops-settings">
      <Box title="告警阈值" note={thresholdsOk ? "Edison 看过了" : "默认值是我的建议，等 Edison 看过"}>
        {settings.rules.map((r) => {
          const o = rule(r.id);
          return (
            <div key={r.id} className="grid gap-2 px-4 py-3 sm:grid-cols-[13rem_minmax(0,1fr)] sm:gap-6">
              <div className="flex flex-col gap-1">
                <label className="flex items-center gap-2 text-sm font-medium text-foreground">
                  <input type="checkbox" checked={o.enabled} onChange={(e) => setRule(r.id, { enabled: e.target.checked })} />
                  {r.title}
                </label>
                <select
                  className={cn(inputCls, "h-8 w-36 text-xs")}
                  value={o.level ?? r.level}
                  onChange={(e) => setRule(r.id, { level: e.target.value as AlertLevel })}
                >
                  {(Object.keys(settings.levels) as AlertLevel[]).map((lv) => (
                    <option key={lv} value={lv}>
                      {settings.levels[lv]}
                    </option>
                  ))}
                </select>
              </div>
              <div className="flex flex-wrap gap-x-5 gap-y-2">
                {Object.entries(settings.rule_defaults[r.id] ?? {}).map(([k, def]) => (
                  <label key={k} className="flex items-center gap-2 text-xs text-body">
                    {PARAM_LABELS[k] ?? k}
                    <Num
                      value={o.params[k] ?? r.params[k] ?? def}
                      step={def < 1 ? 0.01 : 1}
                      onChange={(v) => setRule(r.id, { params: { ...o.params, ...(v === null ? {} : { [k]: v }) } })}
                    />
                  </label>
                ))}
                {!Object.keys(settings.rule_defaults[r.id] ?? {}).length ? <span className="text-xs text-muted-foreground">没有要调的数</span> : null}
              </div>
            </div>
          );
        })}
        <label className="flex items-center gap-2 px-4 py-3 text-sm text-body">
          <input type="checkbox" checked={thresholdsOk} onChange={(e) => setThresholdsOk(e.target.checked)} />
          这些阈值我看过了
        </label>
      </Box>

      <Box title="运维数据留多久" note="单位天；到期每天 04:10 自动删（业务的事件记录不在这里删）">
        {RETENTION.map((x) => (
          <label key={x.key} className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm text-body">
            {x.label}
            <Num value={retention[x.key]} onChange={(v) => setRetention({ ...retention, [x.key]: v ?? retention[x.key] })} />
          </label>
        ))}
      </Box>

      <Box title="备份" note={`现在的引擎：${settings.backup_env.engine === "restic" ? "restic" : "内置兜底（只有数据库）"}`}>
        <label className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm text-body">
          每天几点备份（北京时间）
          <input type="time" className={cn(inputCls, "w-32")} value={backup.time} onChange={(e) => setBackup({ ...backup, time: e.target.value })} />
        </label>
        <label className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm text-body">
          留最近几天的日备
          <Num value={backup.keep_daily} onChange={(v) => setBackup({ ...backup, keep_daily: v ?? backup.keep_daily })} />
        </label>
        <label className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm text-body">
          留最近几周的周备
          <Num value={backup.keep_weekly} onChange={(v) => setBackup({ ...backup, keep_weekly: v ?? backup.keep_weekly })} />
        </label>
        <label className="flex items-center justify-between gap-3 px-4 py-2.5 text-sm text-body">
          隔几天做一次恢复演练
          <Num value={backup.drill_every_days} onChange={(v) => setBackup({ ...backup, drill_every_days: v ?? backup.drill_every_days })} />
        </label>
      </Box>

      <Box title="客户数据保存期限" note="只数、不删：天数是我的建议，要等法务和财务确认；发票、付款记录不编数">
        {life.map((it, i) => (
          <div key={it.key} className="grid gap-2 px-4 py-3 sm:grid-cols-[minmax(0,1fr)_9rem_8rem] sm:items-center sm:gap-4">
            <div className="flex min-w-0 flex-col gap-0.5">
              <span className="text-sm text-foreground">{it.label}</span>
              <span className="text-xs text-muted-foreground">{it.how}</span>
            </div>
            <label className="flex items-center gap-2 text-xs text-body">
              {it.days === null && it.confirm_by === "财务" ? (
                <span className="text-muted-foreground">待财务确认</span>
              ) : (
                <>
                  <Num value={it.days} w="w-20" placeholder="一直留" onChange={(v) => setLife(life.map((x, j) => (j === i ? { ...x, days: v } : x)))} />天
                </>
              )}
            </label>
            <div className="flex flex-col gap-1">
              <label className="flex items-center gap-2 text-xs text-body">
                <input
                  type="checkbox"
                  checked={confirmed.includes(it.key)}
                  onChange={(e) => setConfirmed(e.target.checked ? [...confirmed, it.key] : confirmed.filter((k) => k !== it.key))}
                />
                {it.confirm_by}已确认
              </label>
              {expired[it.key] !== undefined && expired[it.key] !== null ? (
                <span className="text-xs text-muted-foreground">过期的有 {expired[it.key]} 条</span>
              ) : null}
            </div>
          </div>
        ))}
      </Box>

      <div>
        <Button size="sm" onClick={save} disabled={busy}>
          {busy ? <Loader2 className="animate-spin" /> : null}
          保存设置
        </Button>
      </div>
    </div>
  );
}
