import { ArrowDown, ArrowRight } from "lucide-react";
import { useRef, type ReactNode } from "react";

import type { SiteMedia } from "@/lib/site-media";
import { cn } from "@/lib/utils";

import { Caption } from "./Band";
import { useReducedMotion, useSeenOnce } from "./motion";
import { Pic } from "./Pic";

/** 原文截图上要划高亮的地方（占图宽高的比例；用 PyMuPDF 在原论文 PDF 上搜到那一句，按裁切框换算） */
export interface Mark {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface CompareProps {
  original: { media: SiteMedia; label: ReactNode; marks?: Mark[] };
  result: { media: SiteMedia; label: ReactNode };
  /** 图注编号，如「图 1」 */
  no?: string;
  caption?: ReactNode;
  source?: ReactNode;
  /** side：左原文 5 栏、右汇报页 7 栏（原文是窄长的段落）；stack：原文在上、汇报页在下（原文是宽表） */
  layout?: "side" | "stack";
}

/**
 * 「原文这样写 → 我们画成」一组（官网v2方案.md H2，生成清单 R2）：左边原文截图白纸原样放（不加我们的标签、不替读者总结），
 * 右边我们的页。滚到这一组：原文里对应那一句从左往右划一道浅蓝高亮（700ms），再让右边的页淡入上移。
 * 系统「减少动态效果」打开时直接全显示；不动也看得懂。
 */
export function Compare({ original, result, no, caption, source, layout = "side" }: CompareProps) {
  const ref = useRef<HTMLDivElement>(null);
  const reduce = useReducedMotion();
  const seen = useSeenOnce(ref, 0.35) || reduce;
  const stack = layout === "stack";
  return (
    <figure className="m-0">
      <div
        ref={ref}
        className={cn(
          "grid items-center gap-6",
          stack ? "mx-auto max-w-[52rem] gap-5" : "md:grid-cols-[minmax(0,5fr)_auto_minmax(0,7fr)] md:gap-6 lg:gap-8",
        )}
      >
        <div className="min-w-0">
          <p className="mb-3 text-[13px] font-medium tracking-[0.04em] text-muted-foreground">{original.label}</p>
          <div className="relative overflow-hidden rounded-sm bg-background outline outline-1 -outline-offset-1 outline-border">
            <Pic media={original.media} sizes={stack ? "(min-width: 900px) 832px, 92vw" : "(min-width: 1152px) 440px, (min-width: 768px) 40vw, 92vw"} />
            {(original.marks ?? []).map((m, i) => (
              <span
                key={i}
                aria-hidden
                className={cn(
                  "pointer-events-none absolute origin-left bg-highlight mix-blend-multiply",
                  reduce ? "" : "transition-transform duration-[var(--dur-mark)] ease-site",
                  seen ? "scale-x-100" : "scale-x-0",
                )}
                style={{
                  left: `${m.x * 100}%`,
                  top: `${(m.y - 0.004) * 100}%`,
                  width: `${m.w * 100}%`,
                  height: `${(m.h + 0.008) * 100}%`,
                  transitionDelay: reduce ? undefined : `${i * 60}ms`,
                }}
              />
            ))}
          </div>
        </div>
        <span aria-hidden className={cn("flex justify-center text-muted-foreground", stack ? "" : "md:pt-7")}>
          {stack ? <ArrowDown className="size-5" /> : <><ArrowDown className="size-5 md:hidden" /><ArrowRight className="hidden size-5 md:block" /></>}
        </span>
        <div
          className={cn(
            "min-w-0",
            reduce ? "" : "transition-[opacity,transform] duration-[var(--dur-swap)] ease-site",
            seen ? "translate-y-0 opacity-100" : "translate-y-3 opacity-0",
          )}
          style={{ transitionDelay: reduce ? undefined : `${(original.marks?.length ?? 0) * 60 + 450}ms` }}
        >
          <p className="mb-3 text-[13px] font-medium tracking-[0.04em] text-muted-foreground">{result.label}</p>
          <Pic
            media={result.media}
            sizes={stack ? "(min-width: 900px) 832px, 92vw" : "(min-width: 1152px) 640px, (min-width: 768px) 56vw, 92vw"}
            className="rounded-sm shadow-figure outline outline-1 -outline-offset-1 outline-border"
          />
        </div>
      </div>
      {caption || no ? (
        <Caption no={no} source={source} className={cn("mt-5 max-w-2xl", stack && "mx-auto max-w-[52rem]")}>
          {caption}
        </Caption>
      ) : null}
    </figure>
  );
}
