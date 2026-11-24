import { useState, type FormEvent, type ReactNode } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { Textarea } from "@/components/ui/textarea";
import type { AdminPack, AdminTakedown, AdminUnlock, GatherConfig, GatherOverview, PackDraft } from "@/lib/site-types";

function when(iso: string | null) {
  if (!iso) return "";
  return new Date(iso).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function Section({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="mt-8">
      <h2 className="text-base font-semibold">{title}</h2>
      {hint ? <p className="mt-1 text-sm text-muted-foreground">{hint}</p> : null}
      <div className="mt-3">{children}</div>
    </section>
  );
}

/* ---------------------------------------------------------------- 聚人数 */

export function GatherNumbers({ data }: { data: GatherOverview | null }) {
  if (!data) return <Skeleton className="h-24 w-full max-w-3xl" />;
  const big: [string, number][] = [
    ["来访", data.visits],
    ["转发带来的新访客", data.share_new_visitors],
    ["点了要全部图库", data.unlock_requested],
    ["交了截图", data.unlock_evidence],
    ["发出链接", data.unlock_sent],
    ["图库带来的订单", data.orders_from_tuku],
  ];
  return (
    <div className="max-w-4xl">
      <div className="grid grid-cols-2 gap-6 sm:grid-cols-3">
        {big.map(([label, n]) => (
          <div key={label}>
            <div className="text-2xl font-semibold text-foreground tabular-nums">{n}</div>
            <div className="text-sm text-muted-foreground">{label}</div>
          </div>
        ))}
      </div>
      <Section title={`最近 ${data.days} 天从哪来`}>
        <ul className="flex flex-col gap-1 text-sm">
          {data.visits_by_src.map((r) => (
            <li key={r.src} className="flex justify-between gap-4 border-b py-1.5 text-body">
              <span>{r.src}</span>
              <span className="tabular-nums">{r.n}</span>
            </li>
          ))}
          {data.visits_by_src.length === 0 ? <li className="text-muted-foreground">还没有来访。</li> : null}
        </ul>
      </Section>
      <Section title="点去下单页、官网" hint="位置→目标；去下单页的订单上记 source=tuku_位置">
        <ul className="flex flex-col gap-1 text-sm">
          {data.cta_clicks.map((r) => (
            <li key={r.what} className="flex justify-between gap-4 border-b py-1.5 text-body">
              <span>{r.what}</span>
              <span className="tabular-nums">{r.n}</span>
            </li>
          ))}
          {data.cta_clicks.length === 0 ? <li className="text-muted-foreground">还没有人点。</li> : null}
        </ul>
      </Section>
      <Section title="谁来搜的">
        <p className="text-sm text-body">
          网站 {data.search_by_caller.web ?? 0} · 开放接口 {data.search_by_caller.open ?? 0} · 插件 {data.search_by_caller.ai ?? 0} · skill{" "}
          {data.search_by_caller.skill ?? 0}
        </p>
      </Section>
      {data.top_sharers.length ? (
        <Section title="带人最多的分享码">
          <p className="text-sm text-body">{data.top_sharers.map((t) => `${t.share_code}（${t.visits} 人）`).join("、")}</p>
        </Section>
      ) : null}
    </div>
  );
}

/* ---------------------------------------------------------------- 领取列表 */

export interface UnlockListProps {
  items: AdminUnlock[] | null;
  onMark: (evidenceId: number, mark: "ok" | "fake") => Promise<void>;
  onPush: (unlockId: number, on: string) => Promise<void>;
}

export function UnlockList({ items, onMark, onPush }: UnlockListProps) {
  const [busy, setBusy] = useState(0);
  if (!items) return <Skeleton className="h-40 w-full max-w-4xl" />;
  if (items.length === 0) return <p className="text-sm text-muted-foreground">还没有人点「要全部图库？」。</p>;
  async function run(id: number, fn: () => Promise<void>) {
    setBusy(id);
    try {
      await fn();
    } finally {
      setBusy(0);
    }
  }
  return (
    <ul className="max-w-4xl">
      {items.map((u) => (
        <li key={u.id} className="flex flex-col gap-3 border-b py-4 sm:flex-row">
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
              <span className="font-medium text-foreground">{u.share_code}</span>
              <Badge variant={u.stage === "sent" ? "default" : "outline"}>{u.stage_label}</Badge>
              <span className="text-muted-foreground">{when(u.created_at)}</span>
              {u.src ? <span className="text-muted-foreground">来源 {u.src}</span> : null}
              <span className="text-muted-foreground">带来 {u.share_visits} 人</span>
              {u.resend_count ? <span className="text-muted-foreground">重发 {u.resend_count} 次</span> : null}
            </div>
            {u.reason ? <p className="mt-1 text-sm text-body">{u.reason}</p> : null}
            {u.evidence.length ? (
              <div className="mt-2 flex flex-wrap gap-3">
                {u.evidence.map((e) => (
                  <div key={e.id} className="flex flex-col items-start gap-1">
                    <a href={e.url} target="_blank" rel="noreferrer">
                      <img src={e.url} alt="转发截图" className="h-24 w-auto rounded-md border bg-card object-contain" />
                    </a>
                    <div className="flex gap-1">
                      <Button size="sm" variant={e.mark === "ok" ? "default" : "outline"} disabled={busy === u.id} onClick={() => run(u.id, () => onMark(e.id, "ok"))}>
                        没问题
                      </Button>
                      <Button size="sm" variant={e.mark === "fake" ? "destructive" : "outline"} disabled={busy === u.id} onClick={() => run(u.id, () => onMark(e.id, "fake"))}>
                        假的
                      </Button>
                    </div>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
          <div className="flex shrink-0 flex-wrap gap-2 sm:flex-col sm:items-end">
            {u.actions.map((a) => (
              <Button key={a.on} size="sm" variant={a.on === "admin_pass" ? "default" : "outline"} disabled={busy === u.id} onClick={() => run(u.id, () => onPush(u.id, a.on))}>
                {a.label}
              </Button>
            ))}
          </div>
        </li>
      ))}
    </ul>
  );
}

/* ---------------------------------------------------------------- 网盘链接 */

export interface PackPanelProps {
  items: AdminPack[] | null;
  waiting: number;
  gzhReply: { keyword: string; text: string; missing: string } | null;
  onRelease: (d: PackDraft) => Promise<void>;
  onDeactivate: (id: number) => Promise<void>;
}

export function PackPanel({ items, waiting, gzhReply, onRelease, onDeactivate }: PackPanelProps) {
  const [d, setD] = useState<PackDraft>({ version: "", tier: "full", url: "", extract_code: "", count: 0, note: "" });
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setPending(true);
    setError("");
    try {
      await onRelease(d);
      setD({ ...d, url: "", extract_code: "" });
    } catch (err) {
      setError(err instanceof Error ? err.message : "没贴上");
    } finally {
      setPending(false);
    }
  }
  return (
    <div className="max-w-4xl">
      {waiting ? <p className="mb-4 text-sm font-medium text-destructive">有 {waiting} 个人核验过了在等链接：贴上全量包的链接就自动补发。</p> : null}
      <form onSubmit={submit} className="grid gap-4 rounded-md border p-4 sm:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="pk-version">版本</Label>
          <Input id="pk-version" value={d.version} onChange={(e) => setD({ ...d, version: e.target.value })} placeholder="2026.11" required />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="pk-tier">哪一档</Label>
          <select
            id="pk-tier"
            value={d.tier}
            onChange={(e) => setD({ ...d, tier: e.target.value as PackDraft["tier"] })}
            className="h-9 rounded-md border bg-background px-3 text-sm"
          >
            <option value="full">全量（转发的人拿）</option>
            <option value="lite">小包（公众号回复关键词拿）</option>
          </select>
        </div>
        <div className="flex flex-col gap-1.5 sm:col-span-2">
          <Label htmlFor="pk-url">网盘分享链接</Label>
          <Input id="pk-url" value={d.url} onChange={(e) => setD({ ...d, url: e.target.value })} placeholder="从网盘「分享」里复制完整链接（https:// 开头）" required />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="pk-code">提取码</Label>
          <Input id="pk-code" value={d.extract_code} onChange={(e) => setD({ ...d, extract_code: e.target.value })} maxLength={16} />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="pk-count">几张图</Label>
          <Input id="pk-count" type="number" value={d.count || ""} onChange={(e) => setD({ ...d, count: Number(e.target.value) || 0 })} />
        </div>
        {error ? <p className="text-sm text-destructive sm:col-span-2">{error}</p> : null}
        <div className="sm:col-span-2">
          <Button type="submit" disabled={pending}>
            {pending ? "贴上去…" : "贴上，这一版上线"}
          </Button>
        </div>
      </form>
      <Section title="已经贴过的" hint="同一版本同一档再贴就是改链接（旧链接被屏蔽时用）；每档只有一条在用">
        {!items ? (
          <Skeleton className="h-16 w-full" />
        ) : items.length === 0 ? (
          <p className="text-sm text-muted-foreground">还没贴过。</p>
        ) : (
          <ul>
            {items.map((p) => (
              <li key={p.id} className="flex flex-wrap items-center gap-3 border-b py-2 text-sm">
                <span className="font-medium text-foreground">{p.version}</span>
                <span>{p.tier === "full" ? "全量" : "小包"}</span>
                <span className="min-w-0 flex-1 truncate text-body">{p.url}</span>
                <span className="text-muted-foreground">发了 {p.grants} 次</span>
                {p.active ? (
                  <Button size="sm" variant="outline" onClick={() => onDeactivate(p.id)}>
                    下线
                  </Button>
                ) : (
                  <span className="text-muted-foreground">已下线</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </Section>
      <Section title={`公众号关键词回复（关键词「${gzhReply?.keyword ?? "图库"}」）`} hint="在公众号后台「自动回复 → 关键词回复」里贴这段；每次发新版改一次">
        {gzhReply?.missing ? (
          <p className="text-sm text-muted-foreground">{gzhReply.missing}</p>
        ) : (
          <Textarea readOnly value={gzhReply?.text ?? ""} rows={4} />
        )}
      </Section>
    </div>
  );
}

/* ---------------------------------------------------------------- 聚人设置 */

export interface GatherConfigFormProps {
  config: GatherConfig | null;
  onSave: (values: Record<string, unknown>) => Promise<void>;
}

export function GatherConfigForm({ config, onSave }: GatherConfigFormProps) {
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);
  if (!config) return <Skeleton className="h-60 w-full max-w-3xl" />;
  const v = (k: string) => (k in values ? values[k] : config.values[k]);
  const set = (k: string, val: unknown) => setValues((s) => ({ ...s, [k]: val }));
  async function save(e: FormEvent) {
    e.preventDefault();
    setPending(true);
    setError("");
    try {
      await onSave(values);
      setValues({});
    } catch (err) {
      setError(err instanceof Error ? err.message : "没保存上");
    } finally {
      setPending(false);
    }
  }
  const texts = Object.keys(config.labels).filter((k) => typeof config.values[k] === "string" && k !== "verifier");
  return (
    <form onSubmit={save} className="flex max-w-3xl flex-col gap-5">
      <div className="flex flex-col gap-1.5">
        <Label htmlFor="cfg-verifier">{config.labels.verifier}</Label>
        <select
          id="cfg-verifier"
          value={String(v("verifier"))}
          onChange={(e) => set("verifier", e.target.value)}
          className="h-9 rounded-md border bg-background px-3 text-sm"
        >
          {Object.entries(config.verifiers).map(([k, label]) => (
            <option key={k} value={k}>
              {label}
            </option>
          ))}
        </select>
        <p className="text-xs text-muted-foreground">改这一项就换核验方式，流程不用动；之后新点「要全部图库？」的人按新的走。</p>
      </div>
      <label className="flex items-center gap-2 text-sm text-body">
        <input type="checkbox" checked={Boolean(v("unlock_enabled"))} onChange={(e) => set("unlock_enabled", e.target.checked)} />
        {config.labels.unlock_enabled}（第一次被微信拦就关掉，改成转发自愿再申诉）
      </label>
      {(["share_visits_n", "takedown_hours"] as const).map((k) => (
        <div key={k} className="flex flex-col gap-1.5">
          <Label htmlFor={`cfg-${k}`}>{config.labels[k]}</Label>
          <Input id={`cfg-${k}`} type="number" value={String(v(k))} onChange={(e) => set(k, Number(e.target.value))} className="max-w-32" />
        </div>
      ))}
      {texts.map((k) => (
        <div key={k} className="flex flex-col gap-1.5">
          <Label htmlFor={`cfg-${k}`}>{config.labels[k]}</Label>
          {String(v(k)).length > 40 ? (
            <Textarea id={`cfg-${k}`} value={String(v(k))} onChange={(e) => set(k, e.target.value)} rows={3} />
          ) : (
            <Input id={`cfg-${k}`} value={String(v(k))} onChange={(e) => set(k, e.target.value)} />
          )}
        </div>
      ))}
      {error ? <p className="text-sm text-destructive">{error}</p> : null}
      <div>
        <Button type="submit" disabled={pending || Object.keys(values).length === 0}>
          {pending ? "保存中…" : "保存"}
        </Button>
      </div>
    </form>
  );
}

/* ---------------------------------------------------------------- 版权下架 */

export interface TakedownListProps {
  items: AdminTakedown[] | null;
  onDecide: (id: number, decision: "hide" | "reject", figureIds?: number[]) => Promise<void>;
}

export function TakedownList({ items, onDecide }: TakedownListProps) {
  const [ids, setIds] = useState<Record<number, string>>({});
  if (!items) return <Skeleton className="h-24 w-full max-w-4xl" />;
  if (items.length === 0) return <p className="text-sm text-muted-foreground">没有版权方来信。</p>;
  return (
    <ul className="max-w-4xl">
      {items.map((t) => (
        <li key={t.id} className="flex flex-col gap-2 border-b py-4">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm">
            <span className="font-medium text-foreground">{t.holder || "（没写权利人）"}</span>
            <span className="text-muted-foreground">{when(t.created_at)} 收到</span>
            {t.decision === "new" ? (
              <Badge variant={t.overdue ? "destructive" : "outline"}>
                {t.overdue ? "已超时" : `还剩 ${t.hours_left ?? "?"} 小时`}
              </Badge>
            ) : (
              <Badge variant="outline">{t.decision === "hidden" ? "已下架" : "没通过"}</Badge>
            )}
            <span className="text-muted-foreground">{t.contact}</span>
          </div>
          <p className="text-sm whitespace-pre-line text-body">{t.figures_text}</p>
          {t.reason ? <p className="text-sm text-muted-foreground">{t.reason}</p> : null}
          {t.decision === "new" ? (
            <div className="flex flex-wrap items-center gap-2">
              <Input
                value={ids[t.id] ?? t.figure_ids.join(" ")}
                onChange={(e) => setIds((s) => ({ ...s, [t.id]: e.target.value }))}
                className="h-8 max-w-64"
                aria-label="图号"
                placeholder="图号，空格隔开"
              />
              <Button
                size="sm"
                onClick={() =>
                  onDecide(t.id, "hide", (ids[t.id] ?? t.figure_ids.join(" ")).split(/[\s,，]+/).filter(Boolean).map(Number))
                }
              >
                下架
              </Button>
              <Button size="sm" variant="outline" onClick={() => onDecide(t.id, "reject")}>
                不通过
              </Button>
            </div>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
