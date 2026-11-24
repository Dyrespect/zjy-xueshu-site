import { Loader2 } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import type { AlertLevel, OpsConfig, OpsSettingsData, ReportPreview } from "@/lib/ops-types";
import { cn } from "@/lib/utils";

export interface OpsReportProps {
  settings: OpsSettingsData;
  preview: ReportPreview | null;
  onSave: (config: Partial<OpsConfig>) => Promise<void>;
  onTestSend: () => Promise<void>;
  onSendNow: () => Promise<void>;
  onRefreshPreview: () => void;
}

const inputCls = "h-9 rounded-md border border-input bg-background px-2.5 text-sm text-foreground outline-none focus-visible:border-ring";
const LEVELS: AlertLevel[] = ["urgent", "today", "info"];

function Row({ label, note, children }: { label: string; note?: string; children: ReactNode }) {
  return (
    <div className="grid gap-2 border-t py-3 first:border-t-0 sm:grid-cols-[11rem_minmax(0,1fr)] sm:gap-6">
      <div className="flex flex-col gap-0.5">
        <span className="text-sm font-medium text-foreground">{label}</span>
        {note ? <span className="text-xs text-muted-foreground">{note}</span> : null}
      </div>
      <div className="flex flex-col gap-2">{children}</div>
    </div>
  );
}

function Check({ checked, onChange, children }: { checked: boolean; onChange: (v: boolean) => void; children: ReactNode }) {
  return (
    <label className="flex items-center gap-2 text-sm text-body">
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} />
      {children}
    </label>
  );
}

/** 飞书汇报：机器人配没配、试发；每日汇报的开关和时间、预览、现在发；哪些告警即时推送、静默多久、每小时最多几条。只吃 props。 */
export function OpsReport({ settings, preview, onSave, onTestSend, onSendNow, onRefreshPreview }: OpsReportProps) {
  const [report, setReport] = useState(settings.config.report);
  const [push, setPush] = useState(settings.config.push);
  const [rules, setRules] = useState(settings.config.rules);
  const [busy, setBusy] = useState("");
  const s = settings.sender;
  const run = async (key: string, fn: () => Promise<void>) => {
    setBusy(key);
    try {
      await fn();
    } finally {
      setBusy("");
    }
  };
  const rulePush = (id: string) => rules[id]?.push ?? true;
  const setRulePush = (id: string, v: boolean) =>
    setRules((r) => ({ ...r, [id]: { enabled: r[id]?.enabled ?? true, level: r[id]?.level ?? null, params: r[id]?.params ?? {}, push: v } }));

  return (
    <div className="flex flex-col gap-6" data-testid="ops-report">
      <section className={cn("flex flex-col gap-2 rounded-lg border px-4 py-3", s.configured ? "" : "border-foreground")}>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="text-sm font-medium text-foreground">
            {s.configured ? `已配置：${s.label}` : "飞书机器人还没配（告警和日报现在只写日志）"}
          </span>
          <Button size="sm" variant="outline" disabled={!s.configured || !!busy} onClick={() => run("test", onTestSend)}>
            {busy === "test" ? <Loader2 className="animate-spin" /> : null}
            试发一条
          </Button>
        </div>
        {s.configured ? (
          <span className="text-xs text-muted-foreground">
            {s.sender === "feishu_app"
              ? `凭证读自${s.source || "底座 FEISHU_APP_FILE"}，发到你和机器人的私聊。凭证是密钥，这里不显示。`
              : `地址读自${s.source || "底座通知设置"}${s.sender === "feishu_webhook" ? `；签名校验：${s.signed ? "开着" : "没开"}` : ""}。地址是密钥，这里不显示。`}
          </span>
        ) : (
          <ol className="list-decimal pl-5 text-xs leading-6 text-body">
            <li>在飞书建一个群（或用现在收通知的群），群设置 → 机器人 → 添加「自定义机器人」，建议勾上「签名校验」。</li>
            <li>把 webhook 地址存进服务器上的一个文件（第一行地址，第二行签名密钥），权限 600。不要贴到聊天里。</li>
            <li>.env 写 OPS_FEISHU_WEBHOOK_FILE=那个文件的路径，重启网站，回来点「试发一条」。</li>
          </ol>
        )}
      </section>

      <section className="flex flex-col gap-1">
        <h2 className="text-sm font-medium text-foreground">每日汇报</h2>
        <div className="rounded-lg border px-4">
          <Row label="发不发">
            <Check checked={report.enabled} onChange={(v) => setReport({ ...report, enabled: v })}>
              每天发一条昨天的汇报
            </Check>
          </Row>
          <Row label="几点发" note="北京时间">
            <input type="time" className={cn(inputCls, "w-32")} value={report.time} onChange={(e) => setReport({ ...report, time: e.target.value })} />
          </Row>
          <Row label="每类列最新几条" note="新建议、待处理事项">
            <input
              type="number"
              min={0}
              max={10}
              className={cn(inputCls, "w-24")}
              value={report.latest_n}
              onChange={(e) => setReport({ ...report, latest_n: Number(e.target.value) })}
            />
          </Row>
        </div>
      </section>

      <section className="flex flex-col gap-1">
        <h2 className="text-sm font-medium text-foreground">即时推送（网站出问题马上说）</h2>
        <div className="rounded-lg border px-4">
          <Row label="推不推">
            <Check checked={push.enabled} onChange={(v) => setPush({ ...push, enabled: v })}>
              出问题马上推到飞书（关了只记录，后台能看）
            </Check>
          </Row>
          <Row label="哪些级别推">
            <div className="flex flex-wrap gap-4">
              {LEVELS.map((lv) => (
                <Check
                  key={lv}
                  checked={push.levels.includes(lv)}
                  onChange={(v) => setPush({ ...push, levels: v ? [...push.levels, lv] : push.levels.filter((x) => x !== lv) })}
                >
                  {settings.levels[lv]}
                </Check>
              ))}
            </div>
          </Row>
          <Row label="哪些告警推" note="不勾的照样记录、后台能看">
            <div className="grid gap-1.5 sm:grid-cols-2">
              {settings.rules.map((r) => (
                <Check key={r.id} checked={rulePush(r.id)} onChange={(v) => setRulePush(r.id, v)}>
                  {r.title}
                  <span className="text-xs text-muted-foreground">（{settings.levels[r.level]}）</span>
                </Check>
              ))}
            </div>
          </Row>
          <Row label="同一个问题多久再提醒" note="还没好才再推；单位分钟">
            <div className="flex flex-wrap gap-4">
              {(["urgent", "today"] as const).map((lv) => (
                <label key={lv} className="flex items-center gap-2 text-sm text-body">
                  {settings.levels[lv]}
                  <input
                    type="number"
                    min={5}
                    className={cn(inputCls, "w-24")}
                    value={push.silence_minutes[lv]}
                    onChange={(e) => setPush({ ...push, silence_minutes: { ...push.silence_minutes, [lv]: Number(e.target.value) } })}
                  />
                </label>
              ))}
            </div>
          </Row>
          <Row label="每小时最多推几条" note="多的合成一句「还有 N 条」，别刷屏">
            <input
              type="number"
              min={1}
              max={100}
              className={cn(inputCls, "w-24")}
              value={push.max_per_hour}
              onChange={(e) => setPush({ ...push, max_per_hour: Number(e.target.value) })}
            />
          </Row>
          <Row label="恢复了说一声">
            <Check checked={push.notify_resolved} onChange={(v) => setPush({ ...push, notify_resolved: v })}>
              「要立刻处理」的好了也推一条
            </Check>
          </Row>
        </div>
        <div>
          <Button size="sm" className="mt-2" disabled={!!busy} onClick={() => run("save", () => onSave({ report, push, rules }))}>
            {busy === "save" ? <Loader2 className="animate-spin" /> : null}
            保存
          </Button>
        </div>
      </section>

      <section className="flex flex-col gap-2">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-sm font-medium text-foreground">日报预览{preview ? `（${preview.day} 的）` : ""}</h2>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" disabled={!!busy} onClick={onRefreshPreview}>
              重新生成
            </Button>
            <Button size="sm" variant="outline" disabled={!s.configured || !!busy} onClick={() => run("send", onSendNow)}>
              {busy === "send" ? <Loader2 className="animate-spin" /> : null}
              现在发一条
            </Button>
          </div>
        </div>
        {preview ? (
          <div className="rounded-lg border px-4 py-3" data-testid="ops-report-preview">
            <p className="text-sm font-medium text-foreground">{preview.message.title}</p>
            {preview.message.sections.map((sec, i) => (
              <div key={i} className="mt-3 flex flex-col gap-1">
                {sec.title ? <p className="text-xs font-medium text-foreground">【{sec.title}】</p> : null}
                {sec.lines.map((ln, j) => (
                  <p key={j} className="text-sm break-words text-body">
                    {ln.text}
                    {ln.link ? (
                      <a className="ml-1 text-primary hover:underline" href={ln.link} target="_blank" rel="noreferrer">
                        打开
                      </a>
                    ) : null}
                  </p>
                ))}
              </div>
            ))}
          </div>
        ) : (
          <p className="rounded-lg border px-4 py-4 text-sm text-muted-foreground">生成中…</p>
        )}
      </section>
    </div>
  );
}
