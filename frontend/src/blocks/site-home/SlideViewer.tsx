import { useEffect, useRef, useState, type ReactNode } from "react";

import type { SiteMedia } from "@/lib/site-media";
import { cn } from "@/lib/utils";

import { useReducedMotion } from "./motion";
import { Pic } from "./Pic";

const SIZES = "(min-width: 1152px) 1056px, 92vw";

export interface ViewerSlide {
  media: SiteMedia;
  /** 缩略图下、读屏读的短名：「第 3 页 · 研究思路与技术路线」 */
  label: string;
}

export interface SlideViewerProps {
  slides: ViewerSlide[];
  /** 台子下面的图注（这份稿是什么、按哪篇论文做的） */
  caption?: ReactNode;
  /** 每页停多久（毫秒） */
  interval?: number;
}

/**
 * 首屏看稿器（官网v2方案.md H1）：浅灰台子上一页大幻灯片 + 下面一排缩略图。
 * 进页后自己翻一遍（每页停 interval，淡入 400ms），翻完回到第 1 页停住——产品自己的动效、只放一次（Apple 英雄视频播完停住）。
 * 鼠标放上去、键盘聚焦在里面、页面切到后台时停；点缩略图就停在那一页。系统「减少动态效果」打开时不自动翻、不淡入。
 */
export function SlideViewer({ slides, caption, interval = 3000 }: SlideViewerProps) {
  const reduce = useReducedMotion();
  const [idx, setIdx] = useState(0);
  const [auto, setAuto] = useState(true);
  const [ready, setReady] = useState(false); // 第一页出来以后再挂后面几页，首屏只下载一张
  const [hold, setHold] = useState(false);
  const steps = useRef(0);

  useEffect(() => {
    if (!auto || reduce || hold || !ready || slides.length < 2) return;
    const t = window.setTimeout(() => {
      steps.current += 1;
      if (steps.current >= slides.length) {
        setIdx(0);
        setAuto(false); // 翻完一遍：回到第 1 页，停
      } else {
        setIdx((i) => (i + 1) % slides.length);
      }
    }, interval);
    return () => window.clearTimeout(t);
  }, [auto, reduce, hold, ready, idx, interval, slides.length]);

  useEffect(() => {
    const vis = () => setHold(document.hidden);
    document.addEventListener("visibilitychange", vis);
    return () => document.removeEventListener("visibilitychange", vis);
  }, []);

  const pick = (i: number) => {
    setAuto(false);
    setIdx(i);
  };

  return (
    <figure
      className="m-0"
      onMouseEnter={() => setHold(true)}
      onMouseLeave={() => setHold(false)}
      onFocusCapture={() => setHold(true)}
      onBlurCapture={() => setHold(false)}
    >
      <div className="rounded-xl bg-card p-[clamp(0.75rem,3.5vw,3rem)]">
        <div className="relative mx-auto aspect-[16/9] max-w-[66rem] overflow-hidden rounded-sm bg-background shadow-figure outline outline-1 -outline-offset-1 outline-border">
          {slides.map((s, i) =>
            i === 0 || ready ? (
              <div
                key={s.media.id}
                aria-hidden={i !== idx}
                className={cn(
                  "absolute inset-0 transition-opacity ease-site",
                  reduce ? "duration-0" : "duration-[var(--dur-swap)]",
                  i === idx ? "opacity-100" : "opacity-0",
                )}
              >
                <Pic
                  media={s.media}
                  priority={i === 0}
                  sizes={SIZES}
                  className="h-full w-full object-cover"
                  decorative={i !== idx}
                />
                {i === 0 ? <ImgReady onReady={() => setReady(true)} id={s.media.id} /> : null}
              </div>
            ) : null,
          )}
        </div>
      </div>
      <div className="mt-4 flex flex-col gap-4 md:flex-row md:items-start md:justify-between md:gap-8">
        {caption ? <figcaption className="max-w-xl text-sm leading-relaxed text-muted-foreground">{caption}</figcaption> : null}
        <div role="group" aria-label="翻页" className="flex shrink-0 gap-2">
          {slides.map((s, i) => (
            <button
              key={s.media.id}
              type="button"
              onClick={() => pick(i)}
              aria-label={s.label}
              aria-pressed={i === idx}
              className={cn(
                "group w-16 shrink-0 cursor-pointer rounded-[3px] p-0.5 transition-colors sm:w-20",
                i === idx ? "bg-foreground" : "bg-border hover:bg-muted-foreground",
              )}
            >
              <span className="block aspect-[16/9] overflow-hidden rounded-[2px] bg-background">
                {/* sizes 跟大图一样：缩略图和大图用同一个文件，不多下载 */}
                {ready || i === 0 ? <Pic media={s.media} sizes={SIZES} decorative className="h-full w-full object-cover" /> : null}
              </span>
            </button>
          ))}
        </div>
      </div>
    </figure>
  );
}

/** 第一页图下载完（或已经在缓存里）就通知一声 */
function ImgReady({ onReady, id }: { onReady: () => void; id: string }) {
  useEffect(() => {
    const img = document.querySelector<HTMLImageElement>(`img[src*="/${id}-"]`);
    if (!img || img.complete) {
      onReady();
      return;
    }
    img.addEventListener("load", onReady, { once: true });
    img.addEventListener("error", onReady, { once: true });
    return () => {
      img.removeEventListener("load", onReady);
      img.removeEventListener("error", onReady);
    };
  }, [onReady, id]);
  return null;
}
