import { useEffect, useRef, useState, type ReactNode } from "react";

import type { SiteMedia } from "@/lib/site-media";
import { cn } from "@/lib/utils";

import { useReducedMotion } from "./motion";
import { Pic } from "./Pic";

export interface FlowStep {
  title: string;
  text: ReactNode;
  /** 这一步的真截图；没有就出占位（只在本机开发时显示） */
  media?: SiteMedia;
  /** 占位上写的「这里放什么」 */
  slot: string;
}

/**
 * 交付四步（官网v2方案.md H5）：桌面上左边四步字往下走，右边一张产品截图钉住，滚到哪步换哪张（DJI/Apple 粘性章节，
 * OpenAI 首页大屏 sticky top 64）。手机取消钉住：一步一段字一张图上下排（DJI 拉到 390 宽溢出，反例）。
 * 当前步加粗、左边竖线跟着走；换图淡入 400ms；系统「减少动态效果」打开时不淡入。
 */
export function FlowChapter({ steps, ratio = "16/10" }: { steps: FlowStep[]; ratio?: string }) {
  const reduce = useReducedMotion();
  const [active, setActive] = useState(0);
  const refs = useRef<(HTMLLIElement | null)[]>([]);

  // 当前步 = 中线已经过了视口中线的最后一步（字走到屏幕中间就换；往回滚也对；还没到第 1 步时就是第 1 步）
  useEffect(() => {
    let raf = 0;
    const update = () => {
      raf = 0;
      const mid = window.innerHeight / 2;
      let a = 0;
      refs.current.forEach((el, i) => {
        if (!el) return;
        const r = el.getBoundingClientRect();
        if (r.top + r.height / 2 < mid) a = i;
      });
      setActive(a);
    };
    const onScroll = () => {
      if (!raf) raf = window.requestAnimationFrame(update);
    };
    update();
    window.addEventListener("scroll", onScroll, { passive: true });
    window.addEventListener("resize", onScroll);
    return () => {
      window.removeEventListener("scroll", onScroll);
      window.removeEventListener("resize", onScroll);
      if (raf) window.cancelAnimationFrame(raf);
    };
  }, [steps.length]);

  return (
    <div className="md:grid md:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] md:gap-12 lg:gap-16">
      <ol className="flex flex-col">
        {steps.map((s, i) => (
          <li
            key={s.title}
            ref={(el) => {
              refs.current[i] = el;
            }}
            data-step={i}
            className="border-t py-8 first:border-t-0 first:pt-0 md:flex md:min-h-[44vh] md:items-center md:border-t-0 md:py-0"
          >
            <div
              className={cn(
                "md:border-l-2 md:pl-6 md:transition-colors md:duration-[var(--dur-swap)]",
                i === active ? "md:border-foreground" : "md:border-border",
              )}
            >
              <p className="text-sm text-muted-foreground tabular-nums">{String(i + 1).padStart(2, "0")}</p>
              {/* 不是当前步时字退成次要灰（不用透明度：透明后对比度不够，axe 会拦） */}
              <h3 className={cn("mt-2 text-xl font-semibold text-foreground md:transition-colors md:duration-[var(--dur-swap)]", i !== active && "md:text-muted-foreground")}>
                {s.title}
              </h3>
              <p className={cn("mt-2 max-w-md leading-[1.8] text-body md:transition-colors md:duration-[var(--dur-swap)]", i !== active && "md:text-muted-foreground")}>{s.text}</p>
              {/* 手机：每步自己的图 */}
              <div className="mt-5 md:hidden">
                <Shot step={s} ratio={ratio} />
              </div>
            </div>
          </li>
        ))}
      </ol>
      {/* 桌面：右边钉住的图 */}
      <div className="hidden md:block">
        <div className="sticky top-[calc(50vh-min(18rem,28vw))]">
          <div className="relative" style={{ aspectRatio: ratio }}>
            {steps.map((s, i) => (
              <div
                key={s.title}
                aria-hidden={i !== active}
                className={cn(
                  "absolute inset-0 transition-opacity ease-site",
                  reduce ? "duration-0" : "duration-[var(--dur-swap)]",
                  i === active ? "opacity-100" : "opacity-0",
                )}
              >
                <Shot step={s} ratio={ratio} decorative={i !== active} />
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function Shot({ step, ratio, decorative }: { step: FlowStep; ratio: string; decorative?: boolean }) {
  return (
    <Pic
      media={step.media}
      slot={step.slot}
      ratio={ratio}
      decorative={decorative}
      sizes="(min-width: 1152px) 640px, (min-width: 768px) 56vw, 92vw"
      className="h-full w-full rounded-sm bg-background object-cover object-top outline outline-1 -outline-offset-1 outline-border"
      style={{ aspectRatio: ratio }}
    />
  );
}
