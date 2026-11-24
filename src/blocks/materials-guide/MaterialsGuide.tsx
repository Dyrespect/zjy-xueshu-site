import { useState } from "react";

import type { MaterialItem, MaterialsGuideView } from "@/lib/shop-types";
import { cn } from "@/lib/utils";

export interface MaterialsGuideProps {
  /** 订单中枢设置里的资料清单（/api/shop/catalog 的 materials）；字一个不在前端写 */
  guide: MaterialsGuideView;
  /** 先看哪个场合（场合 key）；不给就看第一个 */
  initial?: string;
  /** 紧凑：不显示导语（下单页折叠里用） */
  compact?: boolean;
}

function Items({ title, items }: { title: string; items: MaterialItem[] }) {
  if (!items.length) return null;
  return (
    <div>
      <h3 className="text-sm font-semibold text-foreground">{title}</h3>
      <ul className="mt-2 flex flex-col">
        {items.map((it) => (
          <li key={it.text} className="border-t py-2.5 first:border-t-0 first:pt-0">
            <span className="block text-[15px] leading-relaxed text-foreground">{it.text}</span>
            {it.use ? <span className="mt-0.5 block text-sm leading-relaxed text-body">{it.use}</span> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * 下单前准备好这些：先点场合，再看这个场合必须发的、有的话更好的（每样后面半句说用来干什么），
 * 下面是每个场合都要说的几样和「资料齐了才开工」。官网价目页、下单页共用；手机上场合按钮换行排。
 */
export function MaterialsGuide({ guide, initial, compact }: MaterialsGuideProps) {
  const first = guide.occasions.find((o) => o.key === initial) ?? guide.occasions[0];
  const [key, setKey] = useState(first?.key ?? "");
  const occ = guide.occasions.find((o) => o.key === key) ?? first;
  if (!occ) return null;
  return (
    <div className="flex max-w-2xl flex-col gap-5" data-testid="materials-guide">
      {!compact && guide.lead ? <p className="text-base leading-relaxed text-body">{guide.lead}</p> : null}
      <div role="tablist" aria-label="汇报场合" className="flex flex-wrap gap-2">
        {guide.occasions.map((o) => (
          <button
            key={o.key}
            type="button"
            role="tab"
            aria-selected={o.key === occ.key}
            onClick={() => setKey(o.key)}
            className={cn(
              "h-9 rounded-full border px-3.5 text-sm transition-colors",
              o.key === occ.key ? "border-primary bg-highlight font-medium text-foreground" : "bg-background text-body hover:bg-accent",
            )}
          >
            {o.name}
          </button>
        ))}
      </div>
      <div role="tabpanel" aria-label={occ.name} className="grid gap-6 sm:grid-cols-2 sm:gap-8">
        <Items title={guide.must_title} items={occ.must} />
        <Items title={guide.nice_title} items={occ.nice} />
      </div>
      {guide.common.length ? (
        <div className="border-t pt-4">
          <h3 className="text-sm font-semibold text-foreground">{guide.common_title}</h3>
          <ul className="mt-2 grid gap-x-6 gap-y-2 sm:grid-cols-3">
            {guide.common.map((c) => (
              <li key={c.text} className="text-sm leading-relaxed">
                <span className="text-foreground">{c.text}</span>
                {c.use ? <span className="block text-body">{c.use}</span> : null}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
      {guide.rule ? <p className="text-sm leading-relaxed text-muted-foreground">{guide.rule}</p> : null}
    </div>
  );
}
