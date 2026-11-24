import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { DEFAULT_CHOICE, NONE_STYLE, type BriefAdminView, type BriefAnswers } from "@/lib/brief-types";
import { cn } from "@/lib/utils";

export interface BriefAdminProps {
  view: BriefAdminView;
  /** 改了发给客人重新确认 */
  onSendBack: (answers: BriefAnswers, note: string) => Promise<void>;
  /** 代客人确认（客人在聊天里口头说「可以」），note = 依据 */
  onProxy: (note: string) => Promise<void>;
}

const field = "h-8 w-full rounded-md border border-input bg-background px-2.5 text-sm text-foreground outline-none focus-visible:border-ring";

function when(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  return `${d.getMonth() + 1}月${d.getDate()}日 ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

/** 选项的字都从 view.settings 来（后台设置），这里只摆。 */
function Editor({ view, onSave, onCancel }: { view: BriefAdminView; onSave: (a: BriefAnswers, note: string) => Promise<void>; onCancel: () => void }) {
  const [draft, setDraft] = useState<BriefAnswers>(() => structuredClone(view.answers));
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const tag = view.settings.texts.default_tag;
  const set = (key: string, choice: string | string[]) => setDraft((d) => ({ ...d, [key]: { ...d[key], choice } }));
  const val = (key: string) => draft[key]?.choice;
  return (
    <div className="flex flex-col gap-3 rounded-md border px-3 py-3">
      {view.settings.questions.map((q) => (
        <label key={q.key} className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">{q.title}</span>
          {q.kind === "multi" ? (
            <span className="flex flex-wrap gap-x-3 gap-y-1.5">
              {q.options.map((o) => {
                const picks = Array.isArray(val(q.key)) ? (val(q.key) as string[]) : [];
                return (
                  <span key={o.key} className="inline-flex items-center gap-1.5 text-sm text-body">
                    <input
                      type="checkbox"
                      className="accent-primary"
                      checked={picks.includes(o.key)}
                      onChange={(e) => set(q.key, e.target.checked ? [...picks, o.key] : picks.filter((x) => x !== o.key))}
                    />
                    {o.label}
                  </span>
                );
              })}
            </span>
          ) : (
            <select
              className={cn(field, "pr-7")}
              value={typeof val(q.key) === "string" ? (val(q.key) as string) : ""}
              onChange={(e) => set(q.key, e.target.value)}
            >
              <option value="">没选</option>
              <option value={DEFAULT_CHOICE}>{tag}</option>
              {q.kind === "minutes"
                ? view.minutes.options.map((n) => (
                    <option key={n} value={String(n)}>
                      {n} 分钟
                    </option>
                  ))
                : q.options.map((o) => (
                    <option key={o.key} value={o.key}>
                      {o.label}
                    </option>
                  ))}
            </select>
          )}
        </label>
      ))}
      <label className="flex flex-col gap-1">
        <span className="text-xs text-muted-foreground">{view.settings.style.title}</span>
        <select className={cn(field, "pr-7")} value={typeof val("style") === "string" ? (val("style") as string) : ""} onChange={(e) => set("style", e.target.value)}>
          <option value="">没选</option>
          <option value={DEFAULT_CHOICE}>{tag}</option>
          {view.settings.style.samples.map((s) => (
            <option key={s.key} value={s.key}>
              {s.title}
            </option>
          ))}
          <option value={NONE_STYLE}>{view.settings.style.none_label}</option>
        </select>
      </label>
      <label className="flex flex-col gap-1">
        <span className="text-xs text-muted-foreground">告诉客人改了什么（会跟链接一起发过去）</span>
        <input className={field} value={note} maxLength={200} placeholder="比如：时长按你说的改成 20 分钟" onChange={(e) => setNote(e.target.value)} />
      </label>
      <div className="flex gap-2">
        <Button
          size="sm"
          disabled={busy}
          onClick={() => {
            setBusy(true);
            void onSave(draft, note).finally(() => setBusy(false));
          }}
        >
          发给客人重新确认
        </Button>
        <Button size="sm" variant="ghost" onClick={onCancel} disabled={busy}>
          不改了
        </Button>
      </div>
    </div>
  );
}

/**
 * 后台订单详情里的需求卡（09 需求引导）：客人点了什么、确认卡、什么时候谁确认的（客人点 / 代确认 + 依据）；
 * 开工前能改了发给客人重新确认、能代客人确认（必须写依据）。只吃 props。
 */
export function BriefAdmin({ view, onSendBack, onProxy }: BriefAdminProps) {
  const [mode, setMode] = useState<"" | "edit" | "proxy">("");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const done = view.state === "confirmed";
  const status = done
    ? view.confirm_method === "proxy"
      ? "你代客人确认的"
      : `客人自己点了「${view.settings.texts.confirm_label}」`
    : view.state === "sent_back"
      ? "改了发回去了，等客人再确认"
      : view.state === "locked"
        ? "没确认就开工了（老单或手动开工）"
        : "等客人确认";
  return (
    <section className="border-b px-4 py-4 text-sm" aria-label="需求卡" data-testid="brief-admin">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-[15px] font-semibold text-foreground">需求卡</h2>
          <p className={cn("mt-0.5 text-xs", done ? "text-foreground" : "text-muted-foreground")} data-testid="brief-admin-status">
            {status}
            {done && view.confirmed_at ? ` · ${when(view.confirmed_at)}` : ""}
          </p>
          {done && view.confirm_method === "proxy" && view.confirm_note ? (
            <p className="mt-0.5 text-xs text-muted-foreground">依据：{view.confirm_note}</p>
          ) : null}
          {!done && view.condition.detail && view.state !== "locked" ? (
            <p className="mt-0.5 text-xs text-muted-foreground">{view.condition.detail}</p>
          ) : null}
        </div>
        <Button
          variant="outline"
          size="sm"
          className="shrink-0"
          onClick={() => {
            void navigator.clipboard?.writeText(view.url);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1600);
          }}
        >
          {copied ? <Check /> : <Copy />}
          {copied ? "复制好了" : "客人的链接"}
        </Button>
      </div>

      <dl className="mt-3 grid grid-cols-[4.5rem_1fr] gap-x-3 gap-y-1.5">
        {view.card.map((l) => (
          <div key={l.key} className="contents">
            <dt className="text-muted-foreground">{l.label}</dt>
            <dd className={cn("min-w-0", l.missing ? "text-destructive" : l.by_default ? "text-body" : "text-foreground")}>{l.value}</dd>
          </div>
        ))}
      </dl>

      {view.editable ? (
        mode === "edit" ? (
          <div className="mt-3">
            <Editor
              view={view}
              onCancel={() => setMode("")}
              onSave={async (a, note) => {
                await onSendBack(a, note);
                setMode("");
              }}
            />
          </div>
        ) : mode === "proxy" ? (
          <div className="mt-3 flex flex-col gap-2 rounded-md border px-3 py-3">
            <span className="text-xs text-muted-foreground">依据：客人在聊天里怎么说的（会记进确认记录，标明是你代确认）</span>
            <input
              className={field}
              value={reason}
              maxLength={200}
              placeholder="比如：客人在聊天里说「可以，就这样」"
              onChange={(e) => setReason(e.target.value)}
              aria-label="代确认的依据"
            />
            {view.missing.length ? <span className="text-xs text-body">没选的（{view.missing.join("、")}）照推荐值算。</span> : null}
            <div className="flex gap-2">
              <Button
                size="sm"
                disabled={busy || !reason.trim()}
                onClick={() => {
                  setBusy(true);
                  void onProxy(reason.trim())
                    .then(() => setMode(""))
                    .finally(() => setBusy(false));
                }}
                data-testid="brief-proxy-confirm"
              >
                代客人确认
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setMode("")} disabled={busy}>
                算了
              </Button>
            </div>
          </div>
        ) : (
          <div className="mt-3 flex flex-wrap gap-2">
            <Button size="sm" variant="outline" onClick={() => setMode("edit")}>
              改了发给客人确认
            </Button>
            {!done ? (
              <Button size="sm" variant="outline" onClick={() => setMode("proxy")} disabled={!!view.consent_needed} data-testid="brief-proxy">
                代客人确认
              </Button>
            ) : null}
            {!done && view.consent_needed ? (
              <span className="basis-full text-xs leading-relaxed text-body" data-testid="brief-consent-needed">
                客人还没勾「同意材料交给 AI 处理（含境外）」这几项：出境要本人单独同意，不能代确认。把需求卡链接发给客人，让他在确认卡上勾一下、自己确认。
              </span>
            ) : null}
          </div>
        )
      ) : null}

      {view.history.length ? (
        <details className="mt-3">
          <summary className="cursor-pointer text-xs text-muted-foreground">改动和确认记录（{view.history.length}）</summary>
          <ul className="mt-1.5 flex flex-col gap-1 text-xs text-body">
            {view.history.map((h, i) => (
              <li key={i}>
                {when(h.at)} · {h.who} · {h.what}
                {h.note ? `：${h.note}` : ""}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </section>
  );
}
