import { Plus, X } from "lucide-react";

import type { BizConfig, MaterialLine, MaterialsGuideSettings, OccasionRule } from "@/lib/admin-types";

const inputCls = "h-8 w-full min-w-0 rounded-md border border-input bg-background px-2.5 text-sm text-foreground outline-none focus-visible:border-ring";
const numCls = "h-8 w-20 rounded-md border border-input bg-background px-2.5 text-sm text-foreground outline-none focus-visible:border-ring";
const selectCls = "h-8 rounded-md border border-input bg-background px-2 text-sm text-foreground outline-none focus-visible:border-ring";

export interface MaterialsEditorProps {
  cfg: BizConfig;
  /** 能登记成的用途（论文、开题报告、进展……） */
  purposes: string[];
  onChange: (patch: Partial<BizConfig>) => void;
}

const blank = (): MaterialLine => ({ text: "", use: "", purpose: "", key: "" });

function Lines({
  label,
  lines,
  purposes,
  needPurpose,
  onChange,
}: {
  label: string;
  lines: MaterialLine[];
  purposes: string[];
  /** 必须发的：一定要选登记成哪种用途 */
  needPurpose: boolean;
  onChange: (lines: MaterialLine[]) => void;
}) {
  const up = (i: number, patch: Partial<MaterialLine>) => onChange(lines.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  return (
    <div className="flex flex-col gap-2">
      <span className="text-xs text-muted-foreground">{label}</span>
      {lines.map((l, i) => (
        <div key={i} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto_auto] items-center gap-2">
          <input aria-label={`${label}：东西`} className={inputCls} placeholder="东西，如「要讲的论文 PDF」" value={l.text} onChange={(e) => up(i, { text: e.target.value })} />
          <input aria-label={`${label}：用来干什么`} className={inputCls} placeholder="用来干什么（半句）" value={l.use} onChange={(e) => up(i, { use: e.target.value })} />
          <select aria-label={`${label}：登记成`} className={selectCls} value={l.purpose} onChange={(e) => up(i, { purpose: e.target.value })}>
            <option value="">{needPurpose ? "登记成…" : "不登记"}</option>
            {purposes.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
          <button type="button" aria-label="删掉这一样" className="rounded-md p-1.5 text-muted-foreground hover:bg-accent" onClick={() => onChange(lines.filter((_, j) => j !== i))}>
            <X className="size-4" />
          </button>
        </div>
      ))}
      <button type="button" className="inline-flex w-fit items-center gap-1 text-sm text-primary hover:underline" onClick={() => onChange([...lines, blank()])}>
        <Plus className="size-4" />
        加一样
      </button>
    </div>
  );
}

const GUIDE_TEXTS: { key: keyof MaterialsGuideSettings; label: string }[] = [
  { key: "site_title", label: "官网、下单页那一块的标题" },
  { key: "site_lead", label: "官网那一块的导语" },
  { key: "visitor_head", label: "小鱼售前发的开头（{name} = 场合）" },
  { key: "order_head", label: "认领后、场合定了发的开头（{name} = 场合）" },
  { key: "overview_head", label: "场合还不知道时：开头" },
  { key: "overview_tail", label: "场合还不知道时：最后一句" },
  { key: "must_title", label: "「必须发的」小标题" },
  { key: "nice_title", label: "「有的话更好」小标题" },
  { key: "common_title", label: "「每个场合都要说的」小标题（官网）" },
  { key: "received_mark", label: "收到了的标记" },
  { key: "start_rule", label: "最后一句（什么时候开工、时限从哪儿算）" },
  { key: "other_text", label: "没有固定清单的场合（其他）说的话" },
];

/** 后台「各场合要什么」：资料清单的唯一来源（对客人说的字 + 核对用途），官网、下单页、小鱼、认领那句话都从这里出。 */
export function MaterialsEditor({ cfg, purposes, onChange }: MaterialsEditorProps) {
  const g = cfg.materials;
  const upOcc = (name: string, patch: Partial<OccasionRule>) => onChange({ occasions: { ...cfg.occasions, [name]: { ...cfg.occasions[name], ...patch } } });
  const upGuide = (patch: Partial<MaterialsGuideSettings>) => onChange({ materials: { ...g, ...patch } });
  return (
    <div className="flex flex-col gap-6">
      {Object.entries(cfg.occasions).map(([name, r]) => (
        <section key={name} className="flex max-w-4xl flex-col gap-3 rounded-md border px-4 py-3.5">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
            <span className="font-medium text-foreground">{name}</span>
            <label className="inline-flex items-center gap-2 text-sm text-body">
              对客叫法
              <input aria-label={`${name}：对客叫法`} className={`${inputCls} w-36`} value={r.name} onChange={(e) => upOcc(name, { name: e.target.value })} />
            </label>
            <label className="inline-flex items-center gap-2 text-sm text-body">
              不设时间时默认
              <input type="number" min={1} className={numCls} value={r.default_minutes} onChange={(e) => upOcc(name, { default_minutes: Number(e.target.value) })} />
              分钟
            </label>
            <span className="text-xs text-muted-foreground">核对：{r.must.map((m) => m.purpose).filter(Boolean).join("、") || "没有固定清单"}</span>
          </div>
          <Lines label="必须发的（每样选登记成哪种用途，都收到了才算齐）" lines={r.must} purposes={purposes} needPurpose onChange={(must) => upOcc(name, { must })} />
          <Lines label="有的话更好" lines={r.nice} purposes={purposes} needPurpose={false} onChange={(nice) => upOcc(name, { nice })} />
        </section>
      ))}

      <section className="flex max-w-4xl flex-col gap-3">
        <h3 className="text-sm font-semibold text-foreground">每个场合都要说的</h3>
        <p className="text-xs text-muted-foreground">对上资料清单里的一项：必需不必需、客人说没说过看那一项（讲几分钟、哪天汇报是开工必需的）。</p>
        {g.common.map((c, i) => (
          <div key={c.key || i} className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)_6rem] items-center gap-2">
            <input aria-label="每个场合都要说的：东西" className={inputCls} value={c.text}
              onChange={(e) => upGuide({ common: g.common.map((x, j) => (j === i ? { ...x, text: e.target.value } : x)) })} />
            <input aria-label="每个场合都要说的：用来干什么" className={inputCls} value={c.use}
              onChange={(e) => upGuide({ common: g.common.map((x, j) => (j === i ? { ...x, use: e.target.value } : x)) })} />
            <span className="truncate text-xs text-muted-foreground">{c.key}</span>
          </div>
        ))}
        {g.find_refs_line ? (
          <>
            <h3 className="mt-2 text-sm font-semibold text-foreground">买了「帮我找文献」时替掉论文的那一样</h3>
            <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1fr)] gap-2">
              <input aria-label="帮我找文献：东西" className={inputCls} value={g.find_refs_line.text}
                onChange={(e) => upGuide({ find_refs_line: { ...g.find_refs_line!, text: e.target.value } })} />
              <input aria-label="帮我找文献：用来干什么" className={inputCls} value={g.find_refs_line.use}
                onChange={(e) => upGuide({ find_refs_line: { ...g.find_refs_line!, use: e.target.value } })} />
            </div>
          </>
        ) : null}
      </section>

      <section className="flex max-w-2xl flex-col gap-3">
        <h3 className="text-sm font-semibold text-foreground">几句引导</h3>
        {GUIDE_TEXTS.map((t) => (
          <label key={t.key} className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">{t.label}</span>
            <input aria-label={t.label} className={inputCls} value={String(g[t.key] ?? "")} onChange={(e) => upGuide({ [t.key]: e.target.value } as Partial<MaterialsGuideSettings>)} />
          </label>
        ))}
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">官网和总览列哪几个场合、什么顺序（用顿号隔开，写场合名）</span>
          <input aria-label="场合顺序" className={inputCls} value={g.order.join("、")}
            onChange={(e) => upGuide({ order: e.target.value.split(/[、,，\s]+/).map((x) => x.trim()).filter(Boolean) })} />
        </label>
      </section>
    </div>
  );
}
