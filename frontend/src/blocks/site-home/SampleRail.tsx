import { ChevronLeft, ChevronRight } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

import type { SiteMedia } from "@/lib/site-media";
import { cn } from "@/lib/utils";

import { Caption } from "./Band";
import { useReducedMotion } from "./motion";
import { Pic } from "./Pic";

export interface RailItem {
  media: SiteMedia;
  title: string;
  meta: string;
}

/**
 * 样张横滑（官网v2方案.md H3）：一排 16:9 卡片，卡宽约六成屏宽（10-25 定的「一排窄左滑」），CSS scroll-snap，
 * 手指横滑或点前后按钮；每张下「图 n · 这一页 · 出处」。放在深色带里（tone=inverse）。不自动滚、不走马灯。
 * 第一张左边和版心对齐，右边出版心到屏幕边（Apple 产品带的做法）。
 */
export function SampleRail({ items, startNo = 1, label }: { items: RailItem[]; startNo?: number; label: string }) {
  const ref = useRef<HTMLUListElement>(null);
  const reduce = useReducedMotion();
  const [edge, setEdge] = useState({ start: true, end: false });

  const sync = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    setEdge({ start: el.scrollLeft < 8, end: el.scrollLeft + el.clientWidth > el.scrollWidth - 8 });
  }, []);
  useEffect(() => {
    sync();
    window.addEventListener("resize", sync);
    return () => window.removeEventListener("resize", sync);
  }, [sync]);

  const go = (dir: 1 | -1) => {
    const el = ref.current;
    const card = el?.querySelector("li");
    if (!el || !card) return;
    el.scrollBy({ left: dir * (card.getBoundingClientRect().width + 24), behavior: reduce ? "auto" : "smooth" });
  };

  return (
    <div>
      <ul
        ref={ref}
        onScroll={sync}
        aria-label={label}
        tabIndex={0}
        className={cn(
          "flex snap-x snap-mandatory gap-6 overflow-x-auto pb-2 outline-none [scrollbar-width:none] focus-visible:ring-2 focus-visible:ring-inverse-muted [&::-webkit-scrollbar]:hidden",
          // 左右留白 = 版心外边距，第一张和标题左对齐；scroll-padding 让吸附点也对齐版心
          "px-[max(1rem,calc((100vw-72rem)/2+1.5rem))] scroll-px-[max(1rem,calc((100vw-72rem)/2+1.5rem))]",
        )}
      >
        {items.map((it, i) => (
          <li key={it.media.id} className="w-[min(82vw,52rem)] shrink-0 snap-start sm:w-[min(62vw,52rem)]">
            <figure className="m-0">
              <div className="overflow-hidden rounded-sm bg-background">
                <Pic media={it.media} sizes="(min-width: 1360px) 832px, (min-width: 640px) 62vw, 82vw" className="aspect-[16/9] object-cover" />
              </div>
              <Caption tone="inverse" no={`图 ${startNo + i}`} source={it.meta} className="mt-4">
                {it.title}
              </Caption>
            </figure>
          </li>
        ))}
      </ul>
      <div className="mx-auto mt-6 flex max-w-6xl items-center gap-2 px-4 sm:px-6">
        <RailButton label="上一张" disabled={edge.start} onClick={() => go(-1)}>
          <ChevronLeft className="size-5" />
        </RailButton>
        <RailButton label="下一张" disabled={edge.end} onClick={() => go(1)}>
          <ChevronRight className="size-5" />
        </RailButton>
      </div>
    </div>
  );
}

function RailButton({ label, disabled, onClick, children }: { label: string; disabled: boolean; onClick: () => void; children: ReactNode }) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className="inline-flex size-11 cursor-pointer items-center justify-center rounded-full border border-inverse-border text-inverse-foreground transition-colors duration-[var(--dur-quick)] hover:border-inverse-muted disabled:cursor-default disabled:opacity-40"
    >
      {children}
    </button>
  );
}
