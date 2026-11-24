import { Loader2, Plus, X } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import type { BriefOption, BriefQuestion, BriefSample, BriefSettings } from "@/lib/brief-types";
import { cn } from "@/lib/utils";

export interface BriefSettingsFormProps {
  settings: BriefSettings;
  onSave: (s: BriefSettings) => Promise<void>;
}

const text = "h-8 w-full min-w-0 rounded-md border border-input bg-background px-2.5 text-sm text-foreground outline-none focus-visible:border-ring";
const num = "h-8 w-16 rounded-md border border-input bg-background px-2.5 text-sm text-foreground outline-none focus-visible:border-ring";

const TEXT_LABELS: Record<string, string> = {
  page_title: "页面标题",
  page_lead: "页面开头一句",
  entry_label: "兑换页上的按钮",
  entry_hint: "按钮下面的小字",
  chat_todo: "聊天页顶上（没确认）",
  chat_done: "聊天页顶上（确认了）",
  default_label: "每题最后那个选项",
  all_default_label: "第一题上方的快捷按钮",
  default_tag: "确认卡上标推荐值的字",
  card_title: "确认卡标题",
  card_lead: "确认卡上面那句",
  confirm_label: "确认按钮",
  edit_label: "回去改的按钮",
  confirmed_lead: "确认以后那句",
  sent_back_lead: "你改了发回时那句",
};

function Row({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <label className={cn("flex flex-col gap-1", className)}>
      <span className="text-xs text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}

function newKey(prefix: string, used: string[]): string {
  let i = used.length + 1;
  while (used.includes(`${prefix}${i}`)) i += 1;
  return `${prefix}${i}`;
}

/**
 * 后台「设置」里的需求卡（09 需求引导）：每题的标题、选项、示例句、推荐值；样张（缩略图地址、讲的哪篇论文）；
 * 几小时没确认提醒一次；按钮和提示上的字。客人页面全从这里读，前端不写死。只吃 props。
 */
export function BriefSettingsForm({ settings, onSave }: BriefSettingsFormProps) {
  const [s, setS] = useState<BriefSettings>(settings);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  useEffect(() => setS(settings), [settings]);
  const dirty = useMemo(() => JSON.stringify(s) !== JSON.stringify(settings), [s, settings]);

  const upQ = (i: number, patch: Partial<BriefQuestion>) =>
    setS((x) => ({ ...x, questions: x.questions.map((q, j) => (j === i ? { ...q, ...patch } : q)) }));
  const upOpt = (i: number, k: number, patch: Partial<BriefOption>) =>
    upQ(i, { options: s.questions[i].options.map((o, j) => (j === k ? { ...o, ...patch } : o)) });
  const upSample = (k: number, patch: Partial<BriefSample>) =>
    setS((x) => ({ ...x, style: { ...x.style, samples: x.style.samples.map((m, j) => (j === k ? { ...m, ...patch } : m)) } }));

  async function save() {
    setBusy(true);
    setMsg("");
    try {
      await onSave(s);
      setMsg("存好了");
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "没存上");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-6" data-testid="brief-settings">
      <p className="max-w-2xl text-sm text-body">
        客人认领后点开的需求卡就照这里出题。每题最后都有「{s.texts.default_label}」，选了就按这里的推荐值。示例句、样张标题是 Claude 写的草稿，改成你的说法；样张图等官网 v2 定了换成同一批。
      </p>
      <div className="flex flex-wrap gap-x-8 gap-y-3 text-sm text-body">
        <label className="flex items-center gap-2">
          认领后
          <input type="number" min={0} max={72} className={num} value={s.remind_after_hours}
            onChange={(e) => setS({ ...s, remind_after_hours: Number(e.target.value) })} />
          小时没确认，提醒客人一次（0 = 不提醒）
        </label>
        <label className="flex items-center gap-2">
          时长每档
          <input type="number" min={1} max={30} className={num} value={s.minutes_step} onChange={(e) => setS({ ...s, minutes_step: Number(e.target.value) })} />
          分钟，最少
          <input type="number" min={1} max={60} className={num} value={s.minutes_floor} onChange={(e) => setS({ ...s, minutes_floor: Number(e.target.value) })} />
          分钟
        </label>
      </div>

      {s.questions.map((q, i) => (
        <section key={q.key} className="flex max-w-3xl flex-col gap-3 border-t pt-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <Row label="题目">
              <input className={text} value={q.title} onChange={(e) => upQ(i, { title: e.target.value })} />
            </Row>
            <Row label="题目下面的小字">
              <input className={text} value={q.hint} onChange={(e) => upQ(i, { hint: e.target.value })} />
            </Row>
          </div>
          {q.kind === "minutes" ? (
            <p className="text-sm text-body">选项从这单买的时长档带出来（不能超过档位上限）；推荐值是档位上限。</p>
          ) : (
            <>
              <div className="flex flex-col gap-2">
                <div className={cn("grid gap-2 text-xs text-muted-foreground", q.fact ? "grid-cols-[11rem_1fr_7rem_2rem]" : "grid-cols-[11rem_1fr_2rem]")}>
                  <span>选项</span>
                  <span>示例句（客人看的一行小字）</span>
                  {q.fact ? <span>{q.fact === "occasion" ? "写回订单的场合" : "写回订单的语言"}</span> : null}
                  <span />
                </div>
                {q.options.map((o, k) => (
                  <div key={o.key} className={cn("grid items-center gap-2", q.fact ? "grid-cols-[11rem_1fr_7rem_2rem]" : "grid-cols-[11rem_1fr_2rem]")}>
                    <input className={text} aria-label={`${q.title}的选项`} value={o.label} onChange={(e) => upOpt(i, k, { label: e.target.value })} />
                    <input className={text} aria-label={`${o.label}的示例句`} value={o.example} onChange={(e) => upOpt(i, k, { example: e.target.value })} />
                    {q.fact ? (
                      <input className={text} aria-label={`${o.label}写回订单`} value={o.fact} onChange={(e) => upOpt(i, k, { fact: e.target.value })} />
                    ) : null}
                    <Button variant="ghost" size="icon-sm" aria-label={`删掉${o.label}`} disabled={q.options.length <= 1}
                      onClick={() => upQ(i, { options: q.options.filter((_, j) => j !== k) })}>
                      <X />
                    </Button>
                  </div>
                ))}
                <Button variant="ghost" size="sm" className="self-start text-body"
                  onClick={() => upQ(i, { options: [...q.options, { key: newKey("opt", q.options.map((o) => o.key)), label: "新选项", example: "", fact: "", upload: false }] })}>
                  <Plus />
                  加一个选项
                </Button>
              </div>
              <Row label={q.kind === "multi" ? "推荐（可多选，空着 = 你们定）" : "推荐值"} className="max-w-xs">
                {q.kind === "multi" ? (
                  <span className="flex flex-wrap gap-x-3 gap-y-1">
                    {q.options.map((o) => {
                      const d = Array.isArray(q.default) ? q.default : [];
                      return (
                        <span key={o.key} className="inline-flex items-center gap-1.5 text-sm text-body">
                          <input type="checkbox" className="accent-primary" checked={d.includes(o.key)}
                            onChange={(e) => upQ(i, { default: e.target.checked ? [...d, o.key] : d.filter((x) => x !== o.key) })} />
                          {o.label}
                        </span>
                      );
                    })}
                  </span>
                ) : (
                  <select className={cn(text, "pr-7")} value={typeof q.default === "string" ? q.default : ""} onChange={(e) => upQ(i, { default: e.target.value })}>
                    {q.options.map((o) => (
                      <option key={o.key} value={o.key}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                )}
              </Row>
            </>
          )}
        </section>
      ))}

      <section className="flex max-w-3xl flex-col gap-3 border-t pt-4">
        <div className="grid gap-3 sm:grid-cols-2">
          <Row label="样张这一步的标题">
            <input className={text} value={s.style.title} onChange={(e) => setS({ ...s, style: { ...s.style, title: e.target.value } })} />
          </Row>
          <Row label="标题下面的小字">
            <input className={text} value={s.style.hint} onChange={(e) => setS({ ...s, style: { ...s.style, hint: e.target.value } })} />
          </Row>
        </div>
        <p className="text-xs text-muted-foreground">
          只放讲公开论文的组会稿，客人自己没发表的研究一页都不放；图片地址填 /site-assets/… 或 https://…，图不进仓库。
        </p>
        {s.style.samples.map((m, k) => (
          <div key={m.key} className="grid gap-3 rounded-md border p-3 sm:grid-cols-[8rem_1fr_2rem]">
            {m.image ? (
              <img src={m.image} alt={m.title} className="aspect-video w-32 rounded border object-cover object-top" />
            ) : (
              <span className="flex aspect-video w-32 items-center justify-center rounded border bg-card text-xs text-muted-foreground">没有图</span>
            )}
            <div className="grid gap-2 sm:grid-cols-2">
              <Row label="标题"><input className={text} value={m.title} onChange={(e) => upSample(k, { title: e.target.value })} /></Row>
              <Row label="说明"><input className={text} value={m.note} onChange={(e) => upSample(k, { note: e.target.value })} /></Row>
              <Row label="图片地址"><input className={text} value={m.image} onChange={(e) => upSample(k, { image: e.target.value })} /></Row>
              <Row label="讲的哪篇论文"><input className={text} value={m.source} onChange={(e) => upSample(k, { source: e.target.value })} /></Row>
            </div>
            <Button variant="ghost" size="icon-sm" aria-label={`删掉样张${m.title}`}
              onClick={() => setS({ ...s, style: { ...s.style, samples: s.style.samples.filter((_, j) => j !== k),
                default: s.style.default === m.key ? "" : s.style.default } })}>
              <X />
            </Button>
          </div>
        ))}
        <div className="flex flex-wrap items-end gap-4">
          <Button variant="ghost" size="sm" className="text-body" disabled={s.style.samples.length >= 6}
            onClick={() => setS({ ...s, style: { ...s.style, samples: [...s.style.samples,
              { key: newKey("s", s.style.samples.map((x) => x.key)), title: "新样张", note: "", image: "", source: "" }] } })}>
            <Plus />
            加一份样张（最多 6 份）
          </Button>
          <Row label="推荐哪份（空着 = 你们定）" className="w-56">
            <select className={cn(text, "pr-7")} value={s.style.default} onChange={(e) => setS({ ...s, style: { ...s.style, default: e.target.value } })}>
              <option value="">{s.style.default_text}</option>
              {s.style.samples.map((m) => (
                <option key={m.key} value={m.key}>
                  {m.title}
                </option>
              ))}
            </select>
          </Row>
        </div>
      </section>

      <section className="flex max-w-3xl flex-col gap-3 border-t pt-4">
        <div className="grid gap-3 sm:grid-cols-[1fr_1fr_6rem]">
          <Row label="传旧材料这一步的标题"><input className={text} value={s.refs.title} onChange={(e) => setS({ ...s, refs: { ...s.refs, title: e.target.value } })} /></Row>
          <Row label="小字"><input className={text} value={s.refs.hint} onChange={(e) => setS({ ...s, refs: { ...s.refs, hint: e.target.value } })} /></Row>
          <Row label="最多几份">
            <input type="number" min={0} max={20} className={num} value={s.refs.max_files} onChange={(e) => setS({ ...s, refs: { ...s.refs, max_files: Number(e.target.value) } })} />
          </Row>
        </div>
      </section>

      <section className="flex max-w-3xl flex-col gap-2 border-t pt-4">
        <h3 className="text-sm font-semibold text-foreground">页面上的字</h3>
        <div className="grid gap-2 sm:grid-cols-2">
          {Object.entries(s.texts).map(([k, v]) => (
            <Row key={k} label={TEXT_LABELS[k] ?? k}>
              <input className={text} value={v} onChange={(e) => setS({ ...s, texts: { ...s.texts, [k]: e.target.value } })} />
            </Row>
          ))}
        </div>
      </section>

      <div className="flex items-center gap-3">
        <Button disabled={!dirty || busy} onClick={() => void save()}>
          {busy ? <Loader2 className="animate-spin" /> : null}
          存需求卡设置
        </Button>
        {msg ? <span className={cn("text-sm", msg === "存好了" ? "text-body" : "text-destructive")}>{msg}</span> : null}
      </div>
    </div>
  );
}
