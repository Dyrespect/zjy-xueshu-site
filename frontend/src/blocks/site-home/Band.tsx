import type { ReactNode } from "react";

import { cn } from "@/lib/utils";

/**
 * 首页一屏（官网v2方案.md 第二节）：眉题（编号 + 一个词）+ 宋体大标题 + 一句导语，下面一样东西。
 * 一屏一个焦点；上下大留白（64→128px）。tone="inverse" 是全页唯一那条深色带（样张横滑）。
 */
export interface BandProps {
  id?: string;
  /** 眉题前的编号，如 01 */
  no?: string;
  eyebrow?: string;
  title?: ReactNode;
  lead?: ReactNode;
  /** 标题行右边的东西（横滑的前后按钮、「看全部」链接） */
  aside?: ReactNode;
  tone?: "plain" | "inverse" | "card";
  /** 标题区和内容之间不留默认间距（内容自己排） */
  children?: ReactNode;
  className?: string;
  /** 标题区放进版心；内容要出版心（横滑）时设 false 自己排 */
  contained?: boolean;
}

export function Band({ id, no, eyebrow, title, lead, aside, tone = "plain", children, className, contained = true }: BandProps) {
  const inv = tone === "inverse";
  const headId = id ? `${id}-title` : undefined;
  return (
    <section
      id={id}
      aria-labelledby={title ? headId : undefined}
      className={cn(
        "scroll-mt-20 py-[clamp(4rem,3rem+4vw,8rem)]",
        inv && "bg-inverse text-inverse-foreground",
        tone === "card" && "bg-card",
        className,
      )}
    >
      {title || eyebrow ? (
        <div className="mx-auto max-w-6xl px-4 sm:px-6">
          <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between md:gap-12">
            <div className="max-w-3xl">
              {eyebrow ? (
                <p className={cn("flex items-baseline gap-3 text-[13px] font-medium tracking-[0.08em]", inv ? "text-inverse-muted" : "text-muted-foreground")}>
                  {no ? <span className="tabular-nums">{no}</span> : null}
                  {no ? <span aria-hidden className={cn("h-px w-8 self-center", inv ? "bg-inverse-border" : "bg-border")} /> : null}
                  <span>{eyebrow}</span>
                </p>
              ) : null}
              {title ? (
                <h2 id={headId} className={cn("mt-4 font-headline text-headline font-semibold", inv ? "text-inverse-foreground" : "text-foreground")}>
                  {title}
                </h2>
              ) : null}
              {lead ? <p className={cn("mt-4 text-lead", inv ? "text-inverse-muted" : "text-body")}>{lead}</p> : null}
            </div>
            {aside ? <div className="shrink-0">{aside}</div> : null}
          </div>
        </div>
      ) : null}
      {children ? (
        <div className={cn(title || eyebrow ? "mt-[clamp(2.5rem,2rem+2vw,4rem)]" : "", contained && "mx-auto max-w-6xl px-4 sm:px-6")}>{children}</div>
      ) : null}
    </section>
  );
}

/** 宋体标题里按「|」分段、每段不拆开（手机上断在想断的地方）；不用 text-wrap: balance（Safari 会重排） */
export function keep(text: string): ReactNode {
  const parts = text.split("|");
  return parts.map((x, i) => (
    <span key={i} className="inline-block">
      {x}
    </span>
  ));
}

/** 图注：「图 n」加粗 + 一句这页在论证什么 + 出处（Nature 图注、Linear FIG 编号、OpenAI 卡片类型日期） */
export function Caption({ no, children, source, tone = "plain", className }: { no?: string; children?: ReactNode; source?: ReactNode; tone?: "plain" | "inverse"; className?: string }) {
  const inv = tone === "inverse";
  return (
    <figcaption className={cn("text-sm leading-relaxed", inv ? "text-inverse-muted" : "text-muted-foreground", className)}>
      {no ? <span className={cn("mr-2 font-semibold", inv ? "text-inverse-foreground" : "text-foreground")}>{no}</span> : null}
      {children}
      {source ? <span className="mt-1 block text-[13px]">{source}</span> : null}
    </figcaption>
  );
}

/** 大数字 + 一句 + 脚注（Apple 产品页大百分比配页尾脚注；没有出处的数字不放） */
export function Stat({ n, unit, text, note }: { n: string; unit?: string; text: ReactNode; note: ReactNode }) {
  return (
    <div className="grid gap-4 border-t pt-8 md:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] md:gap-8 lg:gap-16">
      <p className="font-headline text-[clamp(3.5rem,2.5rem+4vw,6rem)] leading-none font-semibold text-foreground tabular-nums">
        {n}
        {unit ? <span className="ml-2 align-baseline text-[0.36em] font-semibold">{unit}</span> : null}
      </p>
      <div className="max-w-xl self-end">
        <p className="text-lead text-foreground">
          {text}
          <sup className="ml-0.5 text-xs text-muted-foreground">
            <a href="#stat-note" aria-label="注 1" className="underline underline-offset-2">[1]</a>
          </sup>
        </p>
        <p id="stat-note" className="mt-3 text-[13px] leading-relaxed text-muted-foreground">
          <span className="mr-1 tabular-nums">[1]</span>
          {note}
        </p>
      </div>
    </div>
  );
}
