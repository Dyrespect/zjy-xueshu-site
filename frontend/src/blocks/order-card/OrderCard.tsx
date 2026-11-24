import { Check, Circle, Copy, FileText, Loader2, Upload } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import type { FactoryJob, OrderDetail, OrderPatch, ProductionItem } from "@/lib/admin-types";
import { cnDate, fileSize, msgTime } from "@/lib/intake-types";
import { cn } from "@/lib/utils";

import { Field, NativeSelect, Section, inputCls } from "./bits";

export interface OrderCardProps {
  order: OrderDetail;
  occasions: string[];
  purposes: string[];
  deliverableKinds: string[];
  onPatch: (patch: OrderPatch) => Promise<void>;
  /** 后台给加急 / 收回 */
  onRush: (value: boolean) => Promise<void>;
  onResolveNeed: (index: number) => Promise<void>;
  onPurpose: (fileId: number, purpose: string) => Promise<void>;
  /** 按流程里标了 manual 的连线手动推一步（现在开工、平台已确认收货、发最终版……） */
  onPush: (on: string) => Promise<void>;
  /** 作废：return 撤单（码退回还能用）/ void 退款（码作废） */
  onVoid: (action: "return" | "void") => Promise<void>;
  onUpload: (file: File, kind: string) => Promise<void>;
  onLoadFactoryJobs: () => Promise<FactoryJob[]>;
  onPickFactory: (job: string, filename: string, kind: string) => Promise<void>;
  /** 交这一版：传好的最终版 + 整页图 → 出水印图、发布给客户看 */
  onDeliver: () => Promise<void>;
  /** 作废这一版还没交的文件（传错了、要整版重传） */
  onDiscard: () => Promise<void>;
  /** 发最终版（只有已完成能发） */
  onReleaseFinal: () => Promise<void>;
  /** 不加急的单压着的水印版：现在就发 */
  onReleaseNow?: () => Promise<void>;
}

const QUOTE_SEP = /\n-{3,}\n/;

function fmtHold(iso: string): string {
  const d = new Date(iso);
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${d.getMonth() + 1} 月 ${d.getDate()} 日 ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

interface Draft {
  occasion: string;
  title: string;
  duration_min: string;
  duration_confirmed: boolean;
  present_date: string;
  school: string;
  language: string;
  structure_req: string;
  quotes: string;
  paper_count: string;
  page_count: string;
}

function draftOf(o: OrderDetail): Draft {
  return {
    occasion: o.occasion,
    title: o.title,
    duration_min: o.duration_min == null ? "" : String(o.duration_min),
    duration_confirmed: o.duration_confirmed,
    present_date: o.present_date ?? "",
    school: o.school,
    language: o.language,
    structure_req: o.structure_req,
    quotes: o.requirement_quotes.join("\n---\n"),
    paper_count: o.paper_count == null ? "" : String(o.paper_count),
    page_count: o.page_count == null ? "" : String(o.page_count),
  };
}

function patchOf(o: OrderDetail, d: Draft): OrderPatch {
  const p: OrderPatch = {};
  const base = draftOf(o);
  if (d.occasion !== base.occasion && d.occasion) p.occasion = d.occasion;
  if (d.title !== base.title) p.title = d.title;
  if (d.duration_min !== base.duration_min) {
    if (d.duration_min) p.duration_min = Number(d.duration_min);
    else p.clear_duration = true;
  }
  if (d.duration_confirmed !== base.duration_confirmed) p.duration_confirmed = d.duration_confirmed;
  if (d.present_date !== base.present_date) {
    if (d.present_date) p.present_date = d.present_date;
    else p.clear_present_date = true;
  }
  if (d.school !== base.school) p.school = d.school;
  if (d.language !== base.language) p.language = d.language;
  if (d.structure_req !== base.structure_req) p.structure_req = d.structure_req;
  if (d.quotes !== base.quotes) p.requirement_quotes = d.quotes.split(QUOTE_SEP).map((q) => q.trim()).filter(Boolean);
  if (d.paper_count !== base.paper_count && d.paper_count) p.paper_count = Number(d.paper_count);
  if (d.page_count !== base.page_count && d.page_count) p.page_count = Number(d.page_count);
  return p;
}

function guessKind(name: string): string {
  const n = name.toLowerCase();
  if (n.endsWith(".pptx") || n.endsWith(".ppt")) return "PPT";
  if (n.endsWith(".docx") || n.endsWith(".md") || n.endsWith(".doc")) return "讲稿";
  if (n.endsWith(".pdf")) return "PDF";
  return "其他";
}

const PLATFORM: Record<string, string> = {
  xy: "闲鱼", xhs: "小红书", dy: "抖音", web: "自有网页", fk: "发卡站", manual: "后台手动开单", legacy: "旧数据",
};
const ADDON_BY: Record<string, string> = { bundle: "同一笔买的", code: "加购码", edison: "你给的" };

/** 状态进度条：走过的实心、当前的加粗，作废的写停在哪 */
function StageTrack({ o }: { o: OrderDetail }) {
  const idx = o.stage_track.findIndex((s) => s.key === (o.stage === "void" ? o.voided_from : o.stage));
  return (
    <ol className="flex flex-wrap items-center gap-x-1 gap-y-1 text-xs" aria-label="订单状态">
      {o.stage_track.map((s, i) => (
        <li key={s.key} className="flex items-center gap-1">
          <span
            className={cn(
              i === idx ? "font-semibold text-foreground" : i < idx ? "text-body" : "text-faint",
              i === idx && o.stage === "void" && "line-through",
            )}
          >
            {s.label}
          </span>
          {i < o.stage_track.length - 1 ? <span className="text-faint">›</span> : null}
        </li>
      ))}
    </ol>
  );
}

function Toggle({ on, label, onClick, busy }: { on: boolean; label: string; onClick: () => void; busy?: boolean }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      onClick={onClick}
      disabled={busy}
      className={cn(
        "inline-flex h-8 items-center gap-1.5 rounded-md border px-3 text-sm transition-colors disabled:opacity-50",
        on ? "border-foreground/30 bg-accent font-medium text-foreground" : "bg-background text-body hover:bg-accent",
      )}
    >
      {on ? <Check className="size-3.5" /> : null}
      {label}
    </button>
  );
}

/** 交接到哪了：直接写入 / 待领 / 已领 */
function handoffText(o: OrderDetail): string {
  const h = o.handoff;
  if (!h || h.status === "direct") return `已交给工厂（直接写入）：inbox/${h?.folder || o.handoff_folder}/`;
  if (h.status === "ready") return "交接包待领：Mac 上的 factory_pull.py 来领后进 inbox";
  return `已领到 Mac：inbox/${h.claimed_folder || h.folder}/`;
}

const PROD_WHO: Record<string, string> = { bot: "助手", system: "系统", maker: "制作方", edison: "你" };

/** 制作方会话：助手（业务员）和制作方（做 PPT 的 Claude）之间的全部消息，客户看不到。默认显示最近几条。 */
function ProductionThread({ items }: { items: ProductionItem[] }) {
  const [all, setAll] = useState(false);
  const shown = all ? items : items.slice(-4);
  return (
    <div className="flex flex-col gap-2.5">
      {items.length > shown.length ? (
        <button type="button" className="self-start text-xs text-muted-foreground hover:text-foreground" onClick={() => setAll(true)}>
          看全部 {items.length} 条
        </button>
      ) : null}
      {shown.map((m) => {
        const toMaker = m.direction === "to_maker";
        return (
          <div key={m.id} className={cn("rounded-md px-3 py-2", toMaker ? "bg-card" : "border bg-background")}>
            <div className="flex flex-wrap items-baseline gap-x-1.5 text-xs text-muted-foreground">
              <span className="font-medium text-foreground">{toMaker ? `${PROD_WHO[m.author] ?? "助手"} → 制作方` : `制作方 → 助手`}</span>
              <span>{m.kind}</span>
              <span>{msgTime(m.created_at)}</span>
              {toMaker && !m.read_at ? <span className="text-primary">制作方还没看</span> : null}
              {!toMaker && m.kind !== "成品" && !m.relayed_at ? <span className="text-primary">还没转告客户</span> : null}
            </div>
            <p className={cn("mt-1 text-body whitespace-pre-wrap", m.kind === "开单说明" && !all ? "line-clamp-6" : "")}>{m.text}</p>
            {m.files.map((f) => (
              <a key={f.id} href={f.url} className="mt-0.5 block truncate text-xs text-primary hover:underline">
                {f.name}
              </a>
            ))}
          </div>
        );
      })}
    </div>
  );
}

/** 后台订单卡：发了负责人微信的事、五个开工条件、信息（能直接改）、材料、收钱和排期、制作方会话、交付。 */
export function OrderCard(props: OrderCardProps) {
  const { order: o } = props;
  const [draft, setDraft] = useState<Draft>(() => draftOf(o));
  const [busy, setBusy] = useState<string | null>(null);
  const [kind, setKind] = useState(props.deliverableKinds[0] ?? "PPT");
  const [factoryOpen, setFactoryOpen] = useState(false);
  const [jobs, setJobs] = useState<FactoryJob[] | null>(null);
  const [copied, setCopied] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);

  useEffect(() => setDraft(draftOf(o)), [o]);
  const patch = useMemo(() => patchOf(o, draft), [o, draft]);
  const dirty = Object.keys(patch).length > 0;

  async function act(key: string, fn: () => Promise<void>) {
    setBusy(key);
    try {
      await fn();
    } finally {
      setBusy(null);
    }
  }

  const set = <K extends keyof Draft>(k: K, v: Draft[K]) => setDraft((d) => ({ ...d, [k]: v }));
  const openNeeds = o.needs.map((n, i) => ({ ...n, i })).filter((n) => !n.resolved);
  const rounds = Array.from(new Set(o.deliverables.map((f) => f.round))).sort((a, b) => b - a);
  const started = !!o.started_at;
  const closed = o.stage === "void" || (o.stage === "delivered" && o.revisions_left === 0);
  const pull = o.handoff_mode === "pull";
  const collecting = o.stage === "claimed" || o.stage === "collecting";

  return (
    <div className="flex flex-col text-sm">
      <div className="px-4 pt-4 pb-3">
        <div className="flex items-baseline justify-between gap-2">
          <h2 className="text-[15px] font-semibold text-foreground">
            这单 <span className="font-normal text-muted-foreground">#{o.id}</span>
          </h2>
          <span className="text-sm font-medium text-foreground">{o.status_label}</span>
        </div>
        {o.stage_track.length ? (
          <div className="mt-2">
            <StageTrack o={o} />
          </div>
        ) : null}
        {o.progress ? <p className="mt-1.5 text-body">{o.progress}</p> : null}
        {o.hold_reason ? (
          <p className="mt-2 rounded-md border border-destructive/40 px-2.5 py-1.5 text-destructive">
            暂停：{o.hold_reason}。不开工、不交下一版、不发最终版，等平台退款结果。
          </p>
        ) : null}
        {o.manual.length ? (
          <div className="mt-2.5 flex flex-wrap gap-2">
            {o.manual.map((m) => (
              <Button
                key={m.on}
                size="sm"
                variant="outline"
                disabled={busy === `push${m.on}`}
                onClick={() => {
                  if (window.confirm(`${m.label}？`)) void act(`push${m.on}`, () => props.onPush(m.on));
                }}
              >
                {busy === `push${m.on}` ? <Loader2 className="animate-spin" /> : null}
                {m.label}
              </Button>
            ))}
          </div>
        ) : null}
      </div>

      {openNeeds.length ? (
        <Section title="发了你微信的事">
          <ul className="flex flex-col gap-2">
            {openNeeds.map((n) => (
              <li key={n.i} className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <span className="font-medium text-foreground">{n.type}</span>
                  <span className="text-body">：{n.detail}</span>
                </div>
                <Button size="xs" variant="outline" disabled={busy === `need${n.i}`} onClick={() => act(`need${n.i}`, () => props.onResolveNeed(n.i))}>
                  处理了
                </Button>
              </li>
            ))}
          </ul>
        </Section>
      ) : null}

      {collecting ? (
      <Section title="开工条件">
        <ul className="flex flex-col gap-1.5">
          {o.conditions.map((c) => (
            <li key={c.key} className="flex items-start gap-2">
              {c.ok ? <Check className="mt-0.5 size-4 shrink-0 text-primary" /> : <Circle className="mt-0.5 size-4 shrink-0 text-faint" />}
              <span>
                <span className={c.ok ? "text-foreground" : "text-foreground"}>{c.name}</span>
                <span className="text-muted-foreground">　{c.detail}</span>
              </span>
            </li>
          ))}
        </ul>
      </Section>
      ) : null}

      <Section
        title="信息"
        aside={
          dirty ? (
            <div className="flex gap-1.5">
              <Button size="xs" variant="ghost" onClick={() => setDraft(draftOf(o))}>
                撤销
              </Button>
              <Button size="xs" disabled={busy === "save"} onClick={() => act("save", () => props.onPatch(patch))}>
                保存
              </Button>
            </div>
          ) : null
        }
      >
        <div className="grid grid-cols-2 gap-x-3 gap-y-2.5">
          <Field label="场合">
            <NativeSelect value={draft.occasion} onChange={(e) => set("occasion", e.target.value)}>
              <option value="">没说</option>
              {props.occasions.map((x) => (
                <option key={x} value={x}>
                  {x}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <Field label="时长（分钟）">
            <input type="number" min={1} max={240} className={inputCls} value={draft.duration_min} onChange={(e) => set("duration_min", e.target.value)} />
          </Field>
          {o.duration_default ? (
            <label className="col-span-2 flex items-center gap-2 text-sm text-body">
              <input type="checkbox" className="accent-primary" checked={draft.duration_confirmed} onChange={(e) => set("duration_confirmed", e.target.checked)} />
              默认时长，客户点头了
            </label>
          ) : null}
          <Field label="汇报日期">
            <input type="date" className={inputCls} value={draft.present_date} onChange={(e) => set("present_date", e.target.value)} />
          </Field>
          <Field label="客户原话">
            <span className="flex h-8 items-center truncate text-sm text-body">{o.present_date_text || "—"}</span>
          </Field>
          <Field label="学校">
            <input className={inputCls} value={draft.school} onChange={(e) => set("school", e.target.value)} />
          </Field>
          <Field label="语言">
            <NativeSelect value={draft.language} onChange={(e) => set("language", e.target.value)}>
              <option value="">没说</option>
              <option value="中文">中文</option>
              <option value="英文">英文</option>
              <option value="中英">中英</option>
            </NativeSelect>
          </Field>
          <Field label="篇数">
            <input type="number" min={1} max={50} className={inputCls} value={draft.paper_count} onChange={(e) => set("paper_count", e.target.value)} />
          </Field>
          <Field label="要求页数（内容页）">
            <input type="number" min={1} max={500} className={inputCls} value={draft.page_count} onChange={(e) => set("page_count", e.target.value)} />
          </Field>
          <Field label="题目" wide>
            <input className={inputCls} value={draft.title} onChange={(e) => set("title", e.target.value)} />
          </Field>
          <Field label="页数 / 结构" wide>
            <input className={inputCls} value={draft.structure_req} onChange={(e) => set("structure_req", e.target.value)} />
          </Field>
          <Field label="要求原话（多段用 --- 隔开，原样交给工厂）" wide>
            <textarea
              className="field-sizing-content max-h-72 min-h-16 w-full rounded-md border border-input bg-background px-2.5 py-1.5 text-sm leading-relaxed text-foreground outline-none focus-visible:border-ring"
              value={draft.quotes}
              onChange={(e) => set("quotes", e.target.value)}
            />
          </Field>
        </div>
      </Section>

      <Section title="材料">
        {o.required.length ? (
          <div className="mb-2.5 flex flex-wrap gap-x-3 gap-y-1">
            {o.required.map((r) => (
              <span key={r.purpose} className="inline-flex items-center gap-1">
                {r.ok ? <Check className="size-3.5 text-primary" /> : <Circle className="size-3.5 text-faint" />}
                <span className={r.ok ? "text-foreground" : "text-body"}>{r.purpose}</span>
                {r.ok ? null : <span className="text-muted-foreground">还缺</span>}
              </span>
            ))}
          </div>
        ) : null}
        {o.materials.length ? (
          <ul className="flex flex-col gap-1.5">
            {o.materials.map((f) => (
              <li key={f.id} className="flex items-center gap-2">
                <a href={f.url} target="_blank" rel="noopener noreferrer" className="min-w-0 flex-1 truncate text-foreground hover:underline" title={f.name}>
                  {f.name}
                </a>
                <NativeSelect
                  aria-label={`${f.name} 的用途`}
                  className="h-7 w-24 shrink-0 text-xs"
                  value={f.purpose}
                  onChange={(e) => act(`p${f.id}`, () => props.onPurpose(f.id, e.target.value))}
                >
                  <option value="" disabled>
                    没登记
                  </option>
                  {props.purposes.map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </NativeSelect>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-muted-foreground">还没收到文件</p>
        )}
      </Section>

      <Section title="货号和排期">
        <dl className="mb-3 grid grid-cols-[6.5rem_1fr] gap-x-2 gap-y-1.5">
          <dt className="text-xs leading-5 text-muted-foreground">货号</dt>
          <dd className="text-foreground">
            {o.sku_name || <span className="text-body">没有</span>}
            {o.quoted_price ? <span className="text-body"> · {o.quoted_price} 元</span> : null}
          </dd>
          {o.max_pages ? (
            <>
              <dt className="text-xs leading-5 text-muted-foreground">页数上限</dt>
              <dd className="text-body">{o.max_pages} 页（内容页）</dd>
            </>
          ) : null}
          <dt className="text-xs leading-5 text-muted-foreground">从哪买的</dt>
          <dd className="text-body">
            {PLATFORM[o.platform] ?? (o.platform || "—")}
            {o.platform_order_id ? ` · ${o.platform_order_id}` : ""}
            {o.paid_amount ? ` · 实付 ${o.paid_amount}` : ""}
          </dd>
          <dt className="text-xs leading-5 text-muted-foreground">激活码</dt>
          <dd className={o.code ? "font-medium text-foreground tabular-nums" : "text-body"}>
            {o.code ? `${o.code}${o.redeemed_at ? ` · ${msgTime(o.redeemed_at)}认领` : ""}` : "没有（手动开单）"}
          </dd>
          {o.addons.length ? (
            <>
              <dt className="text-xs leading-5 text-muted-foreground">加购</dt>
              <dd className="text-body">{o.addons.map((a) => `${a.name}（${ADDON_BY[a.by] ?? a.by}）`).join("、")}</dd>
            </>
          ) : null}
          {o.platform_completed_at ? (
            <>
              <dt className="text-xs leading-5 text-muted-foreground">平台已完成</dt>
              <dd className="text-body">{msgTime(o.platform_completed_at)}（发布水印版时直接放最终版）</dd>
            </>
          ) : null}
          {o.delivered_at ? (
            <>
              <dt className="text-xs leading-5 text-muted-foreground">还能改</dt>
              <dd className="text-body">
                {o.revisions_left} 轮{o.extra_revisions ? `（加购过 ${o.extra_revisions} 轮）` : ""}
              </dd>
            </>
          ) : null}
        </dl>
        {!started && !closed ? (
          <div className="flex flex-wrap gap-2">
            <Toggle on={o.rush_by_edison} label="给加急（不看名额）" busy={busy === "rush"} onClick={() => act("rush", () => props.onRush(!o.rush_by_edison))} />
          </div>
        ) : null}
        <p className="mt-3 text-body">
          {started
            ? `${handoffText(o)}${o.due_hours ? `，开工后 ${o.due_hours} 小时内交第一版` : ""}${o.rush ? "（加急）" : ""}`
            : o.queued
              ? `排在 ${cnDate(o.start_date)}开工，开工后 ${o.due_hours ?? "?"} 小时内交第一版`
              : o.plan && collecting
                ? `条件齐了最早 ${cnDate(o.plan.start_date)}开工`
                : ""}
        </p>
      </Section>

      {o.production.length ? (
        <Section title="制作方会话" aside={o.maker_state ? <span className="text-xs text-foreground">{o.maker_state}</span> : undefined}>
          <ProductionThread items={o.production} />
        </Section>
      ) : null}

      <Section
        title="交付"
        aside={
          <button
            type="button"
            className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            onClick={() => {
              void navigator.clipboard?.writeText(o.delivery_url);
              setCopied(true);
              window.setTimeout(() => setCopied(false), 1500);
            }}
          >
            <Copy className="size-3" />
            {copied ? "复制好了" : "复制交付页链接"}
          </button>
        }
      >
        {rounds.length ? (
          <div className="mb-3 flex flex-col gap-2.5">
            {rounds.map((r) => (
              <div key={r}>
                <div className="text-xs text-muted-foreground">
                  第 {r} 版{r > o.delivery_round ? "（还没交）" : ""}
                </div>
                <ul className="mt-1 flex flex-col gap-1">
                  {o.deliverables
                    .filter((f) => f.round === r)
                    .map((f) => (
                      <li key={f.id} className="flex items-center gap-2">
                        <FileText className="size-4 shrink-0 text-muted-foreground" />
                        <a href={f.url} className="min-w-0 flex-1 truncate text-foreground hover:underline">
                          {f.name}
                        </a>
                        <span className="shrink-0 text-xs text-muted-foreground">
                          {f.purpose === "水印版" ? `水印版 · 给客户看` : `${f.purpose} · 最终版`} · {fileSize(f.size)}
                        </span>
                      </li>
                    ))}
                </ul>
              </div>
            ))}
          </div>
        ) : null}

        {o.hold_until ? (
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-md bg-card px-3 py-2" data-testid="order-hold">
            <p className="text-body">
              水印版做好了，{fmtHold(o.hold_until)} 自动发给客人
              <span className="block text-xs text-muted-foreground">不加急的单不早于加急的承诺时间发，免得买了加急的人觉得亏</span>
            </p>
            {props.onReleaseNow ? (
              <Button size="xs" variant="outline" disabled={busy === "release"} onClick={() => act("release", props.onReleaseNow!)}>
                现在就发
              </Button>
            ) : null}
          </div>
        ) : null}

        {o.revisions.length ? (
          <div className="mb-3 flex flex-col gap-2">
            {o.revisions.map((rv) => (
              <div key={rv.id} className="rounded-md bg-card px-3 py-2">
                <div className="text-xs text-muted-foreground">
                  改稿单{rv.free ? "" : "（轮数用完了，只记下）"} · {rv.status === "open" ? "没改完" : "改好了"}
                </div>
                <p className="mt-0.5 whitespace-pre-wrap text-body">{rv.text}</p>
                {rv.files.map((f) => (
                  <a key={f.id} href={f.url} className="mt-0.5 block truncate text-xs text-primary hover:underline">
                    {f.name}
                  </a>
                ))}
              </div>
            ))}
          </div>
        ) : null}

        {!closed ? (
          <div className="flex flex-wrap items-center gap-2">
            <input
              ref={fileRef}
              type="file"
              className="hidden"
              data-testid="deliverable-file"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) void act("upload", () => props.onUpload(f, kind)).finally(() => fileRef.current && (fileRef.current.value = ""));
              }}
            />
            <NativeSelect aria-label="成品类型" className="h-8 w-24" value={kind} onChange={(e) => setKind(e.target.value)}>
              {props.deliverableKinds.map((k) => (
                <option key={k} value={k}>
                  {k}
                </option>
              ))}
            </NativeSelect>
            <Button size="sm" variant="outline" disabled={busy === "upload"} onClick={() => fileRef.current?.click()}>
              {busy === "upload" ? <Loader2 className="animate-spin" /> : <Upload />}
              上传成品
            </Button>
            {pull ? null : (
              <Button
                size="sm"
                variant="outline"
                onClick={() => {
                  setFactoryOpen(true);
                  setJobs(null);
                  props.onLoadFactoryJobs().then(setJobs).catch(() => setJobs([]));
                }}
              >
                从工厂选
              </Button>
            )}
            {o.has_new_deliverable && o.can_submit_package ? (
              <Button size="sm" disabled={busy === "deliver"} onClick={() => act("deliver", props.onDeliver)}>
                {busy === "deliver" ? <Loader2 className="animate-spin" /> : null}
                交这一版
              </Button>
            ) : null}
            {o.has_new_deliverable ? (
              <Button
                size="sm"
                variant="ghost"
                disabled={busy === "discard"}
                onClick={() => {
                  if (window.confirm("这一版还没交给客人的文件（pptx、讲稿、整页图、水印图）全删掉，重新传？")) void act("discard", props.onDiscard);
                }}
              >
                作废这一版没交的
              </Button>
            ) : null}
            {o.stage === "completed" ? (
              <Button size="sm" disabled={busy === "final"} onClick={() => act("final", props.onReleaseFinal)}>
                {busy === "final" ? <Loader2 className="animate-spin" /> : null}
                发最终版
              </Button>
            ) : null}
          </div>
        ) : null}
        {!closed ? (
          <p className="mt-2 text-xs text-muted-foreground">
            交一版要有：可编辑的 PPT（锁着，确认收货后才发）+ 每页整页图（类型选「页图」，长边 1600 以上），系统出水印图后只把交付页链接发给客户。
            {pull ? "网站在服务器上，看不到 Mac 里工厂的成品，做好后从「上传成品」传上来。" : ""}
          </p>
        ) : null}
        {o.received_at ? <p className="mt-2.5 text-body">客户点了「确认收货」</p> : null}
        {o.feedback ? (
          <p className="mt-1 text-body">
            反馈：{String(o.feedback.satisfaction ?? "")} {String(o.feedback.comment ?? "")}
          </p>
        ) : null}
      </Section>

      {o.can_void ? (
        <div className="flex flex-wrap justify-end gap-2 border-t px-4 py-3">
          {o.can_return_code ? (
            <Button
              size="sm"
              variant="ghost"
              className="text-destructive hover:text-destructive"
              onClick={() => {
                if (window.confirm("客户不做了：作废这单，激活码退回去还能再用？")) void act("void-return", () => props.onVoid("return"));
              }}
            >
              撤单（码退回）
            </Button>
          ) : null}
          <Button
            size="sm"
            variant="ghost"
            className="text-destructive hover:text-destructive"
            onClick={() => {
              if (window.confirm("平台退款了：作废这单，激活码也作废，停在现在的进度？")) void act("void-refund", () => props.onVoid("void"));
            }}
          >
            退款作废（码作废）
          </Button>
        </div>
      ) : null}

      <Dialog open={factoryOpen} onOpenChange={setFactoryOpen}>
        <DialogContent className="max-h-[80vh] overflow-y-auto sm:max-w-lg">
          <DialogHeader>
            <DialogTitle>从工厂选成品</DialogTitle>
            <DialogDescription>PPT工厂/jobs/&lt;单&gt;/成品/ 里的文件，选一个复制过来（工厂那边不动）。</DialogDescription>
          </DialogHeader>
          {jobs === null ? (
            <p className="py-6 text-center text-sm text-muted-foreground">在读工厂目录…</p>
          ) : jobs.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">工厂里还没有带成品的单</p>
          ) : (
            <ul className="flex flex-col gap-3">
              {jobs.map((j) => (
                <li key={j.job}>
                  <div className="text-sm font-medium text-foreground">{j.job}</div>
                  <ul className="mt-1 flex flex-col gap-1">
                    {j.files.map((f) => (
                      <li key={f.name} className="flex items-center justify-between gap-2 text-sm">
                        <span className="min-w-0 truncate text-body">
                          {f.name} <span className="text-xs text-muted-foreground">{fileSize(f.size)}</span>
                        </span>
                        <Button
                          size="xs"
                          variant="outline"
                          disabled={busy === `f${j.job}${f.name}`}
                          onClick={() =>
                            act(`f${j.job}${f.name}`, () => props.onPickFactory(j.job, f.name, guessKind(f.name))).then(() => setFactoryOpen(false))
                          }
                        >
                          用这个
                        </Button>
                      </li>
                    ))}
                  </ul>
                </li>
              ))}
            </ul>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
