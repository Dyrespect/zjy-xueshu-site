import { Band, Caption, Compare, keep, Pic } from "@/blocks/site-home";
import { NextLinks, PageHead } from "@/blocks/site-section";
import { MEDIA, mediaSrc } from "@/lib/site-media";

import { SAMPLE_COMPARES, SAMPLE_GROUPS } from "./samples";

/**
 * 样张页（官网v2方案.md 第四节）：按汇报场合分组的栅格，每张下面「图 n · 这一页 · 出处」；点图在新窗口看原图（Nature 做法，不盖黑色弹窗）。
 * 页尾放全部「原文这样写 → 我们画成」。都讲公开论文，说明只写论文出处。
 */
export function SamplesPage() {
  let n = 0;
  return (
    <>
      <PageHead eyebrow="服务" title="样张" lead="都是我们做的，这里只是一部分。按页型分组，每份稿最多放三页；每一页都按公开论文制作，图下写着出处。" />
      <nav aria-label="样张分组" className="mx-auto max-w-6xl px-4 sm:px-6">
        <ul className="flex flex-wrap gap-x-6 gap-y-2 border-t pt-6 text-sm">
          {SAMPLE_GROUPS.map((g) => (
            <li key={g.id}>
              <a href={`#${g.id}`} className="text-body hover:text-foreground">
                {g.title}
              </a>
            </li>
          ))}
          <li>
            <a href="#compare" className="text-body hover:text-foreground">
              原文到汇报页
            </a>
          </li>
        </ul>
      </nav>
      {SAMPLE_GROUPS.map((g) => (
        <Band key={g.id} id={g.id} eyebrow={`${g.items.length} 页`} title={g.title} lead={g.lead} className="py-[clamp(3rem,2.5rem+2vw,5rem)]">
          <ul className="grid gap-x-6 gap-y-10 sm:grid-cols-2 lg:grid-cols-3">
            {g.items.map((it) => {
              n += 1;
              const m = MEDIA[it.key];
              return (
                <li key={it.key}>
                  <figure className="m-0">
                    <a href={mediaSrc(m).src} target="_blank" rel="noopener noreferrer" className="block" aria-label={`看原图：${it.title}`}>
                      <Pic media={m} sizes="(min-width: 1024px) 360px, (min-width: 640px) 45vw, 92vw" className="rounded-sm shadow-figure outline outline-1 -outline-offset-1 outline-border" />
                    </a>
                    <Caption no={`图 ${n}`} source={it.source} className="mt-3">
                      {it.title}
                    </Caption>
                  </figure>
                </li>
              );
            })}
          </ul>
        </Band>
      ))}
      <Band id="compare" tone="card" eyebrow="原文到汇报页" title={keep("原文这样写，|我们画成这样。")} lead="首页放了两组英文原图的，这里是另外几组。">
        <div className="flex flex-col gap-[clamp(4rem,3rem+3vw,6rem)]">
          {SAMPLE_COMPARES.map((c, i) => (
            <Compare
              key={c.result}
              layout={c.layout}
              original={{ media: MEDIA[c.original], label: c.originalLabel }}
              result={{ media: MEDIA[c.result], label: c.resultLabel }}
              no={`对照 ${i + 1}`}
              caption={c.caption}
              source={c.source}
            />
          ))}
        </div>
      </Band>
      <NextLinks
        items={[
          { q: "多少钱", label: "价目", to: "/price" },
          { q: "你会拿到什么", label: "交付说明", to: "/service" },
        ]}
      />
    </>
  );
}
