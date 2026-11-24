import { ArrowLeft, ArrowRight, Check, FileText, Loader2, Paperclip, X } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { CheckRow, ChoiceCard } from "@/components/choice";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  DEFAULT_CHOICE,
  NONE_STYLE,
  type BriefAnswer,
  type BriefQuestion,
  type BriefSample,
  type BriefView,
} from "@/lib/brief-types";
import { cn } from "@/lib/utils";

export interface BriefCardProps {
  view: BriefView;
  /** 点了一题：页面存到后端（存完才往下走） */
  onAnswer: (key: string, answer: BriefAnswer) => Promise<void>;
  onUpload: (file: File, kind: "ref" | "template") => Promise<void>;
  onRemoveFile: (id: number) => Promise<void>;
  /** 「对，开工」 */
  onConfirm: () => Promise<void>;
  /** 第一题上方「全部按推荐，直接看确认卡」：页面把所有题记成按推荐（存完跳到确认卡，还能点一行回去改） */
  onAllDefault?: () => Promise<void>;
  /** 确认以后「回聊天发资料」 */
  onChat?: () => void;
  busy?: boolean;
  error?: string;
  /** 一进来停在哪一步（不给就按填到哪自动算） */
  initialStep?: number;
  /** 确认卡「对，开工」上面的勾选（还没勾过同意的平台单：协议、AI 处理和出境、定制不退）；不给就没有 */
  consent?: ReactNode;
}

type Step =
  | { kind: "question"; q: BriefQuestion }
  | { kind: "style" }
  | { kind: "refs" }
  | { kind: "card" };

const ACCEPT = ".pdf,.doc,.docx,.ppt,.pptx,.potx,.png,.jpg,.jpeg,.webp,.zip,.rar,.7z,.txt,.md";

function answered(view: BriefView, key: string): boolean {
  const c = view.answers[key]?.choice;
  return Array.isArray(c) ? true : !!c;
}

function stepsOf(view: BriefView): Step[] {
  const out: Step[] = view.settings.questions.map((q) => ({ kind: "question", q }) as Step);
  if (view.settings.style.samples.length) out.push({ kind: "style" });
  out.push({ kind: "refs" }, { kind: "card" });
  return out;
}

function firstStep(view: BriefView, steps: Step[]): number {
  if (view.state !== "open") return steps.length - 1;
  const i = steps.findIndex((s) => s.kind === "question" && !answered(view, s.q.key));
  if (i >= 0) return i;
  return Object.keys(view.answers).length ? steps.length - 1 : 0;
}

/** 每一步的标题、说明（标题前不加图标） */
function Head({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="flex flex-col gap-1.5">
      <h2 className="text-xl leading-snug font-semibold text-foreground">{title}</h2>
      {hint ? <p className="text-sm leading-relaxed text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

function Nav({ onBack, next, nextLabel = "下一步", busy, canNext = true }: {
  onBack?: () => void; next?: () => void; nextLabel?: string; busy?: boolean; canNext?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-3 pt-1">
      {onBack ? (
        <Button variant="ghost" className="-ml-3 text-body" onClick={onBack} disabled={busy}>
          <ArrowLeft />
          上一步
        </Button>
      ) : (
        <span />
      )}
      {next ? (
        <Button size="lg" className="h-11 min-w-32 text-[15px]" onClick={next} disabled={busy || !canNext} data-testid="brief-next">
          {busy ? <Loader2 className="animate-spin" /> : null}
          {nextLabel}
          {!busy ? <ArrowRight /> : null}
        </Button>
      ) : null}
    </div>
  );
}

/** 「不知道，按推荐做」那一张：跟选项一样能选，下面一行写推荐的是什么 */
function DefaultCard({ selected, label, sub, onSelect }: { selected: boolean; label: string; sub: string; onSelect: () => void }) {
  return (
    <ChoiceCard selected={selected} onSelect={onSelect} className="border-dashed py-3 sm:py-3.5">
      <span className="pr-6 text-[15px] font-medium text-foreground">{label}</span>
      {sub ? <span className="mt-0.5 text-xs leading-relaxed text-muted-foreground">{sub}</span> : null}
    </ChoiceCard>
  );
}

function SampleImage({ s }: { s: BriefSample }) {
  const [broken, setBroken] = useState(!s.image);
  return broken ? (
    <span className="flex aspect-video w-full items-center justify-center rounded-md border bg-card px-3 text-center text-xs text-muted-foreground">
      {s.title}
    </span>
  ) : (
    <img
      src={s.image}
      alt={`样张：${s.title}`}
      loading="lazy"
      onError={() => setBroken(true)}
      className="aspect-video w-full rounded-md border object-cover object-top"
    />
  );
}

/**
 * 需求卡（客人页面的主体，09 需求引导）：一屏一题，点选就往下走；看样张选风格；传旧材料；最后对着确认卡点「对，开工」。
 * 题目、选项、示例句、推荐值、样张、按钮的字都从 view.settings 来（后端设置），这里不写死。只吃 props。
 */
export function BriefCard({ view, onAnswer, onUpload, onRemoveFile, onConfirm, onAllDefault, onChat, busy, error, initialStep, consent }: BriefCardProps) {
  const steps = useMemo(() => stepsOf(view), [view]);
  const [step, setStep] = useState(() => initialStep ?? firstStep(view, steps));
  const [note, setNote] = useState<Record<string, string>>(() =>
    Object.fromEntries(Object.entries(view.answers).map(([k, a]) => [k, a.note ?? ""])),
  );
  const [pending, setPending] = useState<string>("");
  const top = useRef<HTMLDivElement>(null);
  const t = view.settings.texts;
  const cur = steps[Math.min(step, steps.length - 1)];
  const locked = !view.editable;

  useEffect(() => {
    if (view.state === "sent_back" || view.state === "locked") setStep(steps.length - 1);
  }, [view.state, steps.length]);

  const go = (n: number) => {
    setStep(Math.max(0, Math.min(steps.length - 1, n)));
    top.current?.scrollIntoView({ block: "start", behavior: "smooth" });
  };
  // 从确认卡点一行回来改的：改完直接回确认卡，不用把后面几题再走一遍
  const [fromCard, setFromCard] = useState(false);
  const forward = () => {
    if (fromCard) {
      setFromCard(false);
      go(steps.length - 1);
    } else go(step + 1);
  };
  const choose = async (key: string, answer: BriefAnswer, advance: boolean) => {
    setPending(Array.isArray(answer.choice) ? "" : `${key}:${answer.choice}`);
    try {
      await onAnswer(key, answer);
      if (advance) window.setTimeout(forward, 160);
    } catch {
      /* 没存上：页面上方显示原因，停在这一题 */
    } finally {
      setPending("");
    }
  };
  const ans = (key: string) => view.answers[key]?.choice;
  const progress = Math.round(((Math.min(step, steps.length - 1) + 1) / steps.length) * 100);

  let body: ReactNode = null;
  if (cur.kind === "question") {
    const q = cur.q;
    const a = ans(q.key);
    const isDefault = a === DEFAULT_CHOICE;
    if (q.kind === "single") {
      const rec = q.options.find((o) => o.key === q.default);
      body = (
        <>
          <Head title={q.title} hint={q.hint} />
          <div role="radiogroup" aria-label={q.title} className="grid grid-cols-1 gap-2.5 sm:grid-cols-2">
            {q.options.map((o) => (
              <ChoiceCard key={o.key} selected={a === o.key} onSelect={() => void choose(q.key, { choice: o.key }, true)} className="py-3 sm:py-3.5">
                <span className="pr-6 text-[15px] font-medium text-foreground">{o.label}</span>
                {o.example ? <span className="mt-0.5 text-xs leading-relaxed text-muted-foreground">{o.example}</span> : null}
              </ChoiceCard>
            ))}
          </div>
          <DefaultCard
            selected={isDefault}
            label={t.default_label}
            sub={rec ? `${t.default_tag}：${rec.label}` : ""}
            onSelect={() => void choose(q.key, { choice: DEFAULT_CHOICE }, true)}
          />
          <Nav onBack={step > 0 ? () => go(step - 1) : undefined} next={a ? forward : undefined} busy={busy && !pending} />
        </>
      );
    } else if (q.kind === "minutes") {
      const m = view.minutes;
      body = (
        <>
          <Head title={q.title} hint={view.tier_name ? `${q.hint}（${view.tier_name}档：最多 ${m.high} 分钟）` : q.hint} />
          <div role="radiogroup" aria-label={q.title} className="grid grid-cols-3 gap-2 sm:grid-cols-4">
            {m.options.map((n) => (
              <ChoiceCard key={n} selected={a === String(n)} onSelect={() => void choose(q.key, { choice: String(n) }, true)} className="items-center py-3 sm:py-3">
                <span className="text-[15px] font-medium text-foreground tabular-nums">{n} 分钟</span>
              </ChoiceCard>
            ))}
          </div>
          <DefaultCard
            selected={isDefault}
            label={t.default_label}
            sub={`${t.default_tag}：${m.default} 分钟`}
            onSelect={() => void choose(q.key, { choice: DEFAULT_CHOICE }, true)}
          />
          <Nav onBack={step > 0 ? () => go(step - 1) : undefined} next={a ? forward : undefined} busy={busy && !pending} />
        </>
      );
    } else {
      const picks = Array.isArray(a) ? a : [];
      const save = (choice: string | string[]) => choose(q.key, { choice, note: note[q.key] ?? "" }, false);
      body = (
        <>
          <Head title={q.title} hint={q.hint} />
          <div className="flex flex-col gap-2.5">
            {q.options.map((o) => (
              <CheckRow
                key={o.key}
                checked={picks.includes(o.key)}
                onChange={(on) => void save(on ? [...picks.filter((x) => x !== o.key), o.key] : picks.filter((x) => x !== o.key))}
                title={o.label}
                note={o.example}
              />
            ))}
          </div>
          {q.allow_note ? (
            <Textarea
              aria-label={`${q.title}：补充一句`}
              placeholder={q.note_placeholder}
              value={note[q.key] ?? ""}
              maxLength={200}
              onChange={(e) => setNote((n) => ({ ...n, [q.key]: e.target.value }))}
              className="min-h-14 bg-background text-[15px]"
            />
          ) : null}
          <DefaultCard selected={isDefault} label={t.default_label} sub={`${t.default_tag}：${view.settings.style.default_text}`}
            onSelect={() => void choose(q.key, { choice: DEFAULT_CHOICE, note: note[q.key] ?? "" }, true)} />
          <Nav
            onBack={step > 0 ? () => go(step - 1) : undefined}
            next={() => {
              const n = note[q.key] ?? "";
              const changed = n !== (view.answers[q.key]?.note ?? "") || !view.answers[q.key];
              if (changed && !isDefault) void choose(q.key, { choice: picks, note: n }, true);
              else forward();
            }}
            nextLabel={picks.length || isDefault || (note[q.key] ?? "").trim() ? "下一步" : "跳过"}
            busy={busy}
          />
        </>
      );
    }
  } else if (cur.kind === "style") {
    const st = view.settings.style;
    const a = ans("style");
    const rec = st.samples.find((s) => s.key === st.default);
    body = (
      <>
        <Head title={st.title} hint={st.hint} />
        <div role="radiogroup" aria-label={st.title} className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          {st.samples.map((s) => (
            <ChoiceCard key={s.key} selected={a === s.key} onSelect={() => void choose("style", { choice: s.key }, false)} className="gap-2.5 p-2.5 sm:p-3">
              <SampleImage s={s} />
              <span className="flex flex-col gap-0.5 px-1 pb-0.5">
                <span className="pr-6 text-[15px] font-medium text-foreground">{s.title}</span>
                {s.note ? <span className="text-xs leading-relaxed text-body">{s.note}</span> : null}
                {s.source ? <span className="text-[11px] leading-relaxed text-muted-foreground">{s.source}</span> : null}
              </span>
            </ChoiceCard>
          ))}
        </div>
        <ChoiceCard selected={a === NONE_STYLE} onSelect={() => void choose("style", { choice: NONE_STYLE, note: note.style ?? "" }, false)} className="py-3">
          <span className="text-[15px] font-medium text-foreground">{st.none_label}</span>
        </ChoiceCard>
        {a === NONE_STYLE ? (
          <Textarea
            aria-label={st.none_label}
            placeholder={st.none_placeholder}
            value={note.style ?? ""}
            maxLength={200}
            onChange={(e) => setNote((n) => ({ ...n, style: e.target.value }))}
            className="min-h-14 bg-background text-[15px]"
          />
        ) : null}
        <DefaultCard selected={a === DEFAULT_CHOICE} label={t.default_label} sub={`${t.default_tag}：${rec ? rec.title : st.default_text}`}
          onSelect={() => void choose("style", { choice: DEFAULT_CHOICE }, true)} />
        <Nav
          onBack={() => go(step - 1)}
          next={() => {
            if (a === NONE_STYLE && (note.style ?? "") !== (view.answers.style?.note ?? "")) void choose("style", { choice: NONE_STYLE, note: note.style ?? "" }, true);
            else if (!a) void choose("style", { choice: DEFAULT_CHOICE }, true);
            else forward();
          }}
          busy={busy}
        />
      </>
    );
  } else if (cur.kind === "refs") {
    const r = view.settings.refs;
    const wantsTemplate = view.settings.questions.some((q) => q.options.some((o) => o.upload && ans(q.key) === o.key));
    const refs = view.files.filter((f) => f.kind === "ref");
    const tpls = view.files.filter((f) => f.kind === "template");
    body = (
      <>
        <Head title={r.title} hint={r.hint} />
        {wantsTemplate ? (
          <FilePick label="传模板" files={tpls} busy={busy} onPick={(f) => onUpload(f, "template")} onRemove={onRemoveFile} testid="brief-upload-template" />
        ) : null}
        <FilePick
          label="传旧材料"
          files={refs}
          busy={busy}
          disabled={refs.length >= r.max_files}
          onPick={(f) => onUpload(f, "ref")}
          onRemove={onRemoveFile}
          testid="brief-upload-ref"
        />
        <Nav onBack={() => go(step - 1)} next={forward} nextLabel={refs.length || tpls.length ? "看确认卡" : "不传，看确认卡"} busy={busy} />
      </>
    );
  } else {
    body = (
      <ConfirmCard
        view={view}
        busy={busy}
        locked={locked}
        onConfirm={onConfirm}
        consent={consent}
        onEdit={(key) => {
          const i = steps.findIndex((s) => (s.kind === "question" && s.q.key === key) || (s.kind === "style" && key === "style") || (s.kind === "refs" && key === "refs"));
          setFromCard(i >= 0);
          go(i >= 0 ? i : 0);
        }}
        onChat={onChat}
      />
    );
  }

  return (
    <div ref={top} className="mx-auto flex w-full max-w-xl scroll-mt-4 flex-col gap-6 px-4 pt-7 pb-12 sm:px-6 sm:pt-10">
      <div className="flex flex-col gap-3">
        <div className="flex items-baseline justify-between gap-3">
          <span className="text-xs text-muted-foreground">
            订单 {view.order_no} · {view.sku_name}
          </span>
          {cur.kind !== "card" ? (
            <span className="text-xs text-muted-foreground tabular-nums" data-testid="brief-progress">
              {step + 1} / {steps.length - 1}
            </span>
          ) : null}
        </div>
        {cur.kind !== "card" ? (
          <>
            <div className="h-0.5 w-full overflow-hidden rounded-full bg-border" aria-hidden>
              <div className="h-full bg-primary transition-[width] duration-300" style={{ width: `${progress}%` }} />
            </div>
            {step === 0 ? (
              <div className="flex flex-col gap-1 pt-1">
                <h1 className="font-display text-[26px] leading-tight font-bold tracking-wide text-foreground">{t.page_title}</h1>
                <p className="text-sm leading-relaxed text-body">{t.page_lead}</p>
                {onAllDefault && view.editable && t.all_default_label ? (
                  <Button
                    variant="outline"
                    size="lg"
                    className="mt-3 h-11 w-full border-primary/50 text-[15px] text-primary hover:text-primary sm:w-auto sm:self-start"
                    disabled={busy}
                    data-testid="brief-all-default"
                    onClick={() =>
                      void onAllDefault()
                        .then(() => go(steps.length - 1))
                        .catch(() => undefined)
                    }
                  >
                    {t.all_default_label}
                    <ArrowRight />
                  </Button>
                ) : null}
              </div>
            ) : null}
          </>
        ) : null}
      </div>
      <div className="flex flex-col gap-4">{body}</div>
      {error ? (
        <p role="alert" className="rounded-md border border-destructive/40 px-4 py-3 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}

function FilePick({ label, files, busy, disabled, onPick, onRemove, testid }: {
  label: string; files: BriefView["files"]; busy?: boolean; disabled?: boolean;
  onPick: (f: File) => Promise<void>; onRemove: (id: number) => Promise<void>; testid: string;
}) {
  const input = useRef<HTMLInputElement>(null);
  return (
    <div className="flex flex-col gap-2.5 rounded-lg border px-4 py-3.5">
      <div className="flex items-center justify-between gap-3">
        <span className="text-[15px] font-medium text-foreground">{label}</span>
        <Button variant="outline" size="sm" disabled={busy || disabled} onClick={() => input.current?.click()}>
          <Paperclip />
          选文件
        </Button>
        <input
          ref={input}
          type="file"
          accept={ACCEPT}
          className="sr-only"
          data-testid={testid}
          onChange={(e) => {
            const f = e.target.files?.[0];
            e.target.value = "";
            if (f) void onPick(f);
          }}
        />
      </div>
      {files.length ? (
        <ul className="flex flex-col gap-1.5">
          {files.map((f) => (
            <li key={f.id} className="flex items-center gap-2 text-sm text-body">
              <FileText className="size-4 shrink-0 text-muted-foreground" />
              <span className="min-w-0 flex-1 truncate">{f.name}</span>
              <button
                type="button"
                className="shrink-0 rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
                aria-label={`删掉 ${f.name}`}
                onClick={() => void onRemove(f.id)}
              >
                <X className="size-3.5" />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

/** 需求确认卡：一题一行（后端按模板拼好的），按推荐的标出来；点一行回去改那一题。 */
function ConfirmCard({ view, busy, locked, onConfirm, onEdit, onChat, consent }: {
  view: BriefView; busy?: boolean; locked: boolean; onConfirm: () => Promise<void>; onEdit: (key: string) => void; onChat?: () => void;
  consent?: ReactNode;
}) {
  const t = view.settings.texts;
  const done = view.state === "confirmed";
  const lead = done ? t.confirmed_lead : view.state === "sent_back" ? t.sent_back_lead : locked ? "" : t.card_lead;
  return (
    <div className="flex flex-col gap-5" data-testid="brief-card">
      <div className="flex flex-col gap-1.5">
        <h1 className="font-display text-[26px] leading-tight font-bold tracking-wide text-foreground">{t.card_title}</h1>
        {lead ? <p className="text-[15px] leading-relaxed text-body">{lead}</p> : null}
        {view.state === "sent_back" && view.sent_back_note ? (
          <p className="text-sm leading-relaxed text-foreground">改了：{view.sent_back_note}</p>
        ) : null}
      </div>
      {done ? (
        <div className="flex items-start gap-3 rounded-lg border border-primary/40 bg-highlight/40 px-4 py-3.5" data-testid="brief-confirmed">
          <span className="mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full bg-primary text-primary-foreground">
            <Check className="size-3.5" strokeWidth={3} />
          </span>
          <div className="flex min-w-0 flex-col gap-1 text-sm leading-relaxed">
            <span className="font-medium text-foreground">
              {view.confirm_method === "proxy" ? "负责人按你在聊天里说的代你确认了" : "你确认了"}
              {view.confirmed_at ? `（${fmtTime(view.confirmed_at)}）` : ""}
            </span>
            {view.next ? (
              <span className="text-body">
                {view.next.text}
                {view.next.text.includes("还差") ? `${view.next.where}。` : ""}
              </span>
            ) : null}
          </div>
        </div>
      ) : null}
      <dl className="flex flex-col divide-y rounded-lg border">
        {view.card.map((line) => {
          const canEdit = !locked;
          const inner = (
            <>
              <dt className="w-[4.5rem] shrink-0 text-sm text-muted-foreground">{line.label}</dt>
              <dd className={cn("min-w-0 flex-1 text-[15px] leading-relaxed", line.missing ? "text-destructive" : "text-foreground")}>
                {line.value}
              </dd>
              {canEdit ? <ArrowRight className="mt-1 size-3.5 shrink-0 text-faint" aria-hidden /> : null}
            </>
          );
          return canEdit ? (
            <button
              key={line.key}
              type="button"
              onClick={() => onEdit(line.key)}
              className="flex w-full items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-accent focus-visible:bg-accent focus-visible:outline-none"
              aria-label={`改${line.label}`}
            >
              {inner}
            </button>
          ) : (
            <div key={line.key} className="flex items-start gap-3 px-4 py-3">
              {inner}
            </div>
          );
        })}
      </dl>
      {locked ? (
        <p className="text-sm leading-relaxed text-body">已经开工了，需求卡不能再改；有变化在聊天里跟助手说。</p>
      ) : done ? (
        <div className="flex flex-col gap-2.5 sm:flex-row-reverse">
          {onChat ? (
            <Button size="lg" className="h-11 text-[15px] sm:min-w-40" onClick={onChat} data-testid="brief-to-chat">
              回聊天发资料
              <ArrowRight />
            </Button>
          ) : null}
          <Button variant="outline" size="lg" className="h-11 text-[15px]" onClick={() => onEdit(view.card[0]?.key ?? "")}>
            {t.edit_label}
          </Button>
        </div>
      ) : (
        <>
        {consent ? <div data-consent className="scroll-mt-24 rounded-lg border px-4 py-3.5">{consent}</div> : null}
        <div className="flex flex-col gap-2.5 sm:flex-row-reverse">
          <Button size="lg" className="h-11 text-[15px] sm:min-w-40" disabled={busy || view.missing.length > 0} onClick={() => void onConfirm()} data-testid="brief-confirm">
            {busy ? <Loader2 className="animate-spin" /> : <Check />}
            {t.confirm_label}
          </Button>
          <Button variant="outline" size="lg" className="h-11 text-[15px]" disabled={busy} onClick={() => onEdit(view.card[0]?.key ?? "")} data-testid="brief-edit">
            {t.edit_label}
          </Button>
        </div>
        </>
      )}
      {!done && !locked && view.missing.length ? (
        <p className="text-sm text-destructive">还有没选的：{view.missing.join("、")}</p>
      ) : null}
    </div>
  );
}

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return `${d.getMonth() + 1}月${d.getDate()}日 ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}
