import { useState, type CSSProperties } from "react";

import { mediaSrc, SHOW_SLOTS, type SiteMedia } from "@/lib/site-media";
import { cn } from "@/lib/utils";

export interface PicProps {
  /** 图（lib/site-media.ts 里的一项）；不给 = 这个位置还没有图，只出占位 */
  media?: SiteMedia;
  /** 占位上写的「这里放什么」；也用来在开发时说明这个位置要什么图 */
  slot?: string;
  /** 宽高比（占位用；有图时按图自己的宽高） */
  ratio?: string;
  sizes?: string;
  /** 首屏的图：不懒加载、优先下载 */
  priority?: boolean;
  className?: string;
  imgClassName?: string;
  style?: CSSProperties;
  /** 装饰图（旁边的字已经说了同一件事）：alt 置空 */
  decorative?: boolean;
}

/**
 * 官网的一张图（官网v2方案.md 第六节「图位」）：webp 两档宽度、写明宽高（不跳版）、非首屏懒加载。
 * 图没有（还没做、或者 site_assets.py 没跑）：本机开发时按比例显示「这里放：……」占位，方便以后换；正式构建里整块不出。
 */
export function Pic({ media, slot, ratio, sizes = "100vw", priority, className, imgClassName, style, decorative }: PicProps) {
  const [broken, setBroken] = useState(false);
  if (!media || broken) {
    if (!SHOW_SLOTS) return null;
    return (
      <div
        data-slot-placeholder
        role="img"
        aria-label={`占位：${slot ?? "这里放一张图"}`}
        className={cn("flex items-center justify-center rounded-sm border border-dashed border-muted-foreground bg-card p-4 text-center", className)}
        style={{ aspectRatio: ratio ?? (media ? `${media.w}/${media.h || media.w}` : "16/9"), ...style }}
      >
        <span className="max-w-[28ch] text-sm leading-relaxed text-muted-foreground">
          这里放：{slot ?? media?.alt ?? "一张图"}
          {media && broken ? <span className="mt-1 block text-xs">（图没拷过来：跑 scripts/site_assets.py）</span> : null}
        </span>
      </div>
    );
  }
  const { src, srcSet } = mediaSrc(media);
  return (
    <img
      src={src}
      srcSet={srcSet}
      sizes={sizes}
      width={media.w}
      height={media.h || undefined}
      alt={decorative ? "" : media.alt}
      loading={priority ? "eager" : "lazy"}
      decoding={priority ? "sync" : "async"}
      // React 18 还不认 fetchPriority 这个驼峰属性，用小写直接传给 DOM
      {...(priority ? { fetchpriority: "high" } : {})}
      onError={() => setBroken(true)}
      className={cn("block h-auto w-full", className, imgClassName)}
      style={style}
    />
  );
}
