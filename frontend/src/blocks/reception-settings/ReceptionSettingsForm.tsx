import { Loader2 } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import type { ReceptionIntent, ReceptionKB, ReceptionTry } from "@/lib/reception-types";
import { cn } from "@/lib/utils";

export interface ReceptionSettingsFormProps {
  kb: ReceptionKB;
  onSave: (kb: ReceptionKB) => Promise<void>;
  /** 试一句：客人说的、助手上一句、一条示范回复（空行分条） */
  onTry: (text: string, lastBot: string, reply: string) => Promise<ReceptionTry>;
  /** 换一份样张（第 slot 份，0–2） */
  onUploadSample?: (slot: number, file: File, title: string) => Promise<void>;
}

const text = "h-8 w-full min-w-0 rounded-md border border-input bg-background px-2.5 text-sm text-foreground outline-none focus-visible:border-ring";
const area = "min-h-16 w-full rounded-md border border-input bg-background px-2.5 py-1.5 text-sm leading-relaxed text-foreground outline-none focus-visible:border-ring";
const num = "h-8 w-20 rounded-md border border-input bg-background px-2.5 text-sm text-foreground outline-none focus-visible:border-ring";

const lines = (v: string[]) => v.join("\n");
const unlines = (v: string) => v.split("\n").map((x) => x.trim()).filter(Boolean);

function Row({ label, children, className }: { label: string; children: ReactNode; className?: string }) {
  return (
    <label className={cn("flex flex-col gap-1", className)}>
      <span className="text-xs text-muted-foreground">{label}</span>
      {children}
    </label>
  );
}

function Section({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3 border-t pt-4">
      <div>
        <h3 className="text-sm font-semibold text-foreground">{title}</h3>
        {hint ? <p className="mt-0.5 text-xs text-muted-foreground">{hint}</p> : null}
      </div>
      {children}
    </section>
  );
}

const RHYTHM_FIELDS: [string, string][] = [
  ["first_min_s", "第一条最早几秒后发"],
  ["first_max_s", "第一条最晚几秒后发（白天）"],
  ["typing_chars_per_s", "打字速度（字/秒）"],
  ["read_per_char_s", "读客人的话（秒/字）"],
  ["night_factor", "夜里慢几倍"],
  ["night_max_s", "夜里第一条最晚几秒"],
  ["filler_every_hours", "「我看下哈」几小时最多一次"],
];

/**
 * 后台「设置」里的接待机器人：表明身份的话（三种写法选一个）、小鱼的人设、转负责人、节奏、说话规矩（禁用说法）、
 * 意图卡（怎么认、回什么、引到哪、什么时候转负责人、示范），最后能试一句。只吃 props。
 */
export function ReceptionSettingsForm({ kb, onSave, onTry, onUploadSample }: ReceptionSettingsFormProps) {
  const [s, setS] = useState<ReceptionKB>(kb);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [trial, setTrial] = useState({ text: "", lastBot: "", reply: "" });
  const [tried, setTried] = useState<ReceptionTry | null>(null);
  useEffect(() => setS(kb), [kb]);
  const dirty = useMemo(() => JSON.stringify(s) !== JSON.stringify(kb), [s, kb]);

  const upIntent = (i: number, patch: Partial<ReceptionIntent>) =>
    setS((x) => ({ ...x, intents: x.intents.map((c, j) => (j === i ? { ...c, ...patch } : c)) }));

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
    <div className="flex flex-col gap-5">
      <Section title="表明身份" hint="会话开头说一次（网页聊天顶上一直挂着一行）。法规要求同时写到「AI」和「生成」两样，保存时会查。">
        <Row label="开头那句">
          <textarea className={area} value={s.disclosure.text} onChange={(e) => setS({ ...s, disclosure: { ...s.disclosure, text: e.target.value } })} />
        </Row>
        <Row label="网页聊天顶上那一行">
          <input className={text} value={s.disclosure.web_footer} onChange={(e) => setS({ ...s, disclosure: { ...s.disclosure, web_footer: e.target.value } })} />
        </Row>
      </Section>

      <Section title="样张" hint="客人想看做出来什么样时，小鱼直接发一份。放讲公开论文的免费稿，带水印的 PDF（scripts/make_samples.py 做），不超过 20MB。">
        {s.samples.map((m, i) => (
          <div key={i} className="grid gap-2 rounded-md border px-3 py-2 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
            <Row label={`第 ${i + 1} 份：讲的哪篇`}>
              <input className={text} value={m.title}
                onChange={(e) => setS({ ...s, samples: s.samples.map((x, j) => (j === i ? { ...x, title: e.target.value } : x)) })} />
            </Row>
            <Row label="一句话（什么场合、几页）">
              <input className={text} value={m.about}
                onChange={(e) => setS({ ...s, samples: s.samples.map((x, j) => (j === i ? { ...x, about: e.target.value } : x)) })} />
            </Row>
            <div className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">{m.filename ? `${m.filename} · ${(m.size / 1024 / 1024).toFixed(1)} MB` : "还没传"}</span>
              {onUploadSample ? (
                <label className="cursor-pointer text-sm text-primary hover:text-primary-hover">
                  {m.filename ? "换一份" : "传 PDF"}
                  <input type="file" accept="application/pdf" className="hidden"
                    onChange={(e) => {
                      const f = e.target.files?.[0];
                      if (f) void onUploadSample(i, f, m.title).then(() => setMsg("样张换好了")).catch((err) => setMsg(err instanceof Error ? err.message : "没传上"));
                      e.target.value = "";
                    }} />
                </label>
              ) : null}
            </div>
          </div>
        ))}
        <Row label="顺带说的那句（公众号每天的免费 PPT）">
          <input className={text} value={s.gzh_line} onChange={(e) => setS({ ...s, gzh_line: e.target.value })} />
        </Row>
      </Section>

      <Section title="人设" hint="接待的人是谁、怎么说话。">
        <Row label="名字">
          <input className={text} value={s.persona.name} onChange={(e) => setS({ ...s, persona: { ...s.persona, name: e.target.value } })} />
        </Row>
        <Row label="她是谁、什么口气">
          <textarea className={area} value={s.persona.who} onChange={(e) => setS({ ...s, persona: { ...s.persona, who: e.target.value } })} />
        </Row>
        <Row label="她不做的">
          <textarea className={area} value={s.persona.never} onChange={(e) => setS({ ...s, persona: { ...s.persona, never: e.target.value } })} />
        </Row>
      </Section>

      <Section title="转负责人" hint="退款、投诉、要找真人、特殊情况：发这句和二维码。">
        <Row label="机器人照着说的那句（含微信号）">
          <input className={text} value={s.owner.line} onChange={(e) => setS({ ...s, owner: { ...s.owner, line: e.target.value } })} />
        </Row>
        <label className="flex items-center gap-2 text-sm text-foreground">
          <input
            type="checkbox"
            checked={s.owner.mute_after_handoff}
            onChange={(e) => setS({ ...s, owner: { ...s.owner, mute_after_handoff: e.target.checked } })}
          />
          转了以后机器人先不回这位客人，等你在「对话」里点「交还机器人」
        </label>
      </Section>

      <Section title="回复节奏" hint="从客人最后一条消息算起。按字数估打字时间，长回复分几条发，夜里慢一点。">
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {RHYTHM_FIELDS.map(([k, label]) => (
            <Row key={k} label={label}>
              <input
                type="number"
                step="0.1"
                className={num}
                value={Number(s.rhythm[k] ?? 0)}
                onChange={(e) => setS({ ...s, rhythm: { ...s.rhythm, [k]: Number(e.target.value) } })}
              />
            </Row>
          ))}
          <Row label="夜里从">
            <input className={num} value={String(s.rhythm.night_from)} onChange={(e) => setS({ ...s, rhythm: { ...s.rhythm, night_from: e.target.value } })} />
          </Row>
          <Row label="到">
            <input className={num} value={String(s.rhythm.night_to)} onChange={(e) => setS({ ...s, rhythm: { ...s.rhythm, night_to: e.target.value } })} />
          </Row>
        </div>
      </Section>

      <Section title="说话" hint="禁用说法每行一条，写成「说法｜为什么」。回复里有就让模型重写。">
        <div className="flex flex-wrap gap-3">
          <Row label="一条最多几个字">
            <input type="number" className={num} value={s.style.max_chars_per_msg}
              onChange={(e) => setS({ ...s, style: { ...s.style, max_chars_per_msg: Number(e.target.value) } })} />
          </Row>
          <Row label="网页最多分几条">
            <input type="number" className={num} value={s.style.max_segments.web ?? 3}
              onChange={(e) => setS({ ...s, style: { ...s.style, max_segments: { ...s.style.max_segments, web: Number(e.target.value) } } })} />
          </Row>
          <Row label="微信客服最多分几条">
            <input type="number" className={num} value={s.style.max_segments.wecom ?? 2}
              onChange={(e) => setS({ ...s, style: { ...s.style, max_segments: { ...s.style.max_segments, wecom: Number(e.target.value) } } })} />
          </Row>
        </div>
        <Row label="禁用说法">
          <textarea
            className={cn(area, "min-h-40")}
            value={s.style.banned.map((b) => `${b.text}｜${b.why}`).join("\n")}
            onChange={(e) =>
              setS({
                ...s,
                style: { ...s.style, banned: unlines(e.target.value).map((l) => ({ text: l.split("｜")[0], why: l.split("｜")[1] ?? "" })) },
              })
            }
          />
        </Row>
        <Row label="要查一下时先说的那句（每行一句，随机挑）">
          <textarea className={area} value={lines(s.style.fillers)} onChange={(e) => setS({ ...s, style: { ...s.style, fillers: unlines(e.target.value) } })} />
        </Row>
      </Section>

      <Section title="意图卡" hint="客人会说的话分成这些类。例句每行一句（判断用，也是测试句）；关键词是正则。">
        {s.intents.map((c, i) => (
          <details key={c.id} className="rounded-md border px-3 py-2">
            <summary className="cursor-pointer text-sm text-foreground">
              {c.name} <span className="text-xs text-muted-foreground">· {c.stage} · {c.id}</span>
            </summary>
            <div className="mt-3 grid gap-3 sm:grid-cols-2">
              <Row label="名字">
                <input className={text} value={c.name} onChange={(e) => upIntent(i, { name: e.target.value })} />
              </Row>
              <Row label="一句话说明">
                <input className={text} value={c.desc} onChange={(e) => upIntent(i, { desc: e.target.value })} />
              </Row>
              <Row label="客人会怎么说（每行一句）">
                <textarea className={area} value={lines(c.examples)} onChange={(e) => upIntent(i, { examples: unlines(e.target.value) })} />
              </Row>
              <Row label="关键词（每行一个正则）">
                <textarea className={area} value={lines(c.keywords)} onChange={(e) => upIntent(i, { keywords: unlines(e.target.value) })} />
              </Row>
              <Row label="回什么">
                <textarea className={area} value={c.reply} onChange={(e) => upIntent(i, { reply: e.target.value })} />
              </Row>
              <Row label="回完引到哪">
                <textarea className={area} value={c.next} onChange={(e) => upIntent(i, { next: e.target.value })} />
              </Row>
              <Row label="什么时候转负责人">
                <textarea className={area} value={c.handoff} onChange={(e) => upIntent(i, { handoff: e.target.value })} />
              </Row>
              <Row label="示范（多段用一行 --- 隔开）">
                <textarea
                  className={area}
                  value={c.samples.join("\n---\n")}
                  onChange={(e) => upIntent(i, { samples: e.target.value.split("\n---\n").map((x) => x.trim()).filter(Boolean) })}
                />
              </Row>
              <label className="flex items-center gap-2 text-sm text-foreground">
                <input type="checkbox" checked={c.decisive} onChange={(e) => upIntent(i, { decisive: e.target.checked })} />
                关键词命中就直接定（不等模型）
              </label>
            </div>
          </details>
        ))}
      </Section>

      <div className="flex items-center gap-3">
        <Button disabled={!dirty || busy} onClick={save}>
          {busy ? <Loader2 className="animate-spin" /> : null}
          保存接待机器人设置
        </Button>
        {msg ? <span className="text-sm text-muted-foreground">{msg}</span> : null}
      </div>

      <Section title="试一句" hint="看规则会判成哪类（不调模型）；写一条示范回复，看会几秒后发、有没有禁用说法。用的是已保存的设置。">
        <div className="grid gap-3 sm:grid-cols-3">
          <Row label="客人说">
            <input className={text} value={trial.text} onChange={(e) => setTrial({ ...trial, text: e.target.value })} />
          </Row>
          <Row label="助手上一句（可空）">
            <input className={text} value={trial.lastBot} onChange={(e) => setTrial({ ...trial, lastBot: e.target.value })} />
          </Row>
          <Row label="示范回复（可空，空行分条）">
            <textarea className={area} value={trial.reply} onChange={(e) => setTrial({ ...trial, reply: e.target.value })} />
          </Row>
        </div>
        <Button
          variant="outline"
          size="sm"
          className="self-start"
          disabled={!trial.text.trim()}
          onClick={async () => setTried(await onTry(trial.text, trial.lastBot, trial.reply))}
        >
          试一下
        </Button>
        {tried ? (
          <div className="flex flex-col gap-1 text-sm text-foreground" data-testid="reception-try">
            <p>
              判成：{tried.intents.map((x) => x.name).join("、")}（{tried.how}）
              {tried.answering ? " · 在回答上一问" : ""}
            </p>
            <p className="text-xs text-muted-foreground">
              打分：{tried.scores.map((x) => `${x.name} ${x.score}`).join("、")}
            </p>
            {tried.reply?.map((r, k) => (
              <p key={k}>
                {r.after_s} 秒后：{r.text}
              </p>
            ))}
            {tried.problems?.length ? <p className="text-destructive">要重写：{tried.problems.join("；")}</p> : null}
          </div>
        ) : null}
      </Section>
    </div>
  );
}
