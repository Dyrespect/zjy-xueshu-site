import { ArrowRight } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";

import { cn } from "@/lib/utils";

/**
 * 官网的版面零件（照 psyppt静态站/styles/blocks.css 一节一节搬过来，名字对应 build.py 的区块函数）：
 * page_head 内页大标题、section 细线 + 编号 + 小标题（宽屏标题放左栏）、points 几样并排、steps 一步一步、
 * rows 左一个词右一段、list_num 带 01 编号的条目、next_links 页末「还想知道什么 → 去哪页」、more 文字链接。
 * 只吃 props，不取数；层次靠字号、字重、留白，框只给能点的东西。
 */

/**
 * 内页大标题（官网 v2）：眉题（所在分组）+ 宋体大标题 + 一句导语；给了 media（右边一张图）就左文右图（Nature 首页左块右图），
 * 手机上图在字下面。下面一条细线把页头和正文分开。
 */
export function PageHead({ title, lead, eyebrow, media }: { title: string; lead?: ReactNode; eyebrow?: string; media?: ReactNode }) {
  return (
    <div className="mx-auto max-w-6xl px-4 sm:px-6">
      <div className={cn("pt-10 pb-10 sm:pt-16 sm:pb-14", media && "grid items-end gap-8 md:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] md:gap-12")}>
        <div>
          {eyebrow ? <p className="text-[13px] font-medium tracking-[0.08em] text-muted-foreground">{eyebrow}</p> : null}
          <h1 className={cn("font-headline text-headline font-semibold tracking-[-0.01em] text-foreground", eyebrow && "mt-3")}>{title}</h1>
          {lead ? <p className="mt-4 max-w-2xl text-lead text-body">{lead}</p> : null}
        </div>
        {media ? <div className="min-w-0">{media}</div> : null}
      </div>
    </div>
  );
}

export interface SectionProps {
  title: string;
  /** 编号，如 01；不给就不显示 */
  no?: string;
  id?: string;
  children?: ReactNode;
}

export function Section({ title, no, id, children }: SectionProps) {
  return (
    <section id={id} className="scroll-mt-6 border-t py-12 lg:grid lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)] lg:gap-x-12 lg:py-16">
      <div className="mb-6 flex items-baseline gap-3 lg:mb-0 lg:flex-col lg:gap-2">
        {no ? <span aria-hidden className="text-sm text-muted-foreground tabular-nums">{no}</span> : null}
        <h2 className="font-headline text-2xl leading-snug font-semibold text-foreground">{title}</h2>
      </div>
      <div className="flex min-w-0 flex-col gap-6">{children}</div>
    </section>
  );
}

/** 一段正文（一行最宽 42 字） */
export function Prose({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("max-w-2xl text-base leading-[1.8] text-body [&_p+p]:mt-3", className)}>{children}</div>;
}

export function Note({ children, className }: { children: ReactNode; className?: string }) {
  return <p className={cn("max-w-2xl text-sm leading-relaxed text-muted-foreground", className)}>{children}</p>;
}

export function More({ to, children }: { to: string; children?: ReactNode }) {
  return (
    <p>
      <Link to={to} className="group inline-flex items-center gap-1 font-medium text-primary hover:text-primary-hover">
        {children}
        <ArrowRight aria-hidden className="size-4 transition-transform group-hover:translate-x-0.5" />
      </Link>
    </p>
  );
}

export function Points({ items }: { items: { title: string; text: string }[] }) {
  return (
    <ul className="grid gap-x-10 gap-y-8 sm:grid-cols-2">
      {items.map((it) => (
        <li key={it.title}>
          <div className="font-semibold text-foreground">{it.title}</div>
          <p className="mt-1 text-sm leading-relaxed text-body">{it.text}</p>
        </li>
      ))}
    </ul>
  );
}

export function Steps({ items }: { items: { title: string; text: ReactNode }[] }) {
  return (
    <ol className={cn("grid md:gap-6", items.length === 3 ? "md:grid-cols-3" : "md:grid-cols-4")}>
      {items.map((it, i) => (
        <li key={it.title} className="grid grid-cols-[2rem_minmax(0,1fr)] border-t py-4 md:block md:py-0 md:pt-4">
          <span className="row-span-2 pt-0.5 text-sm text-muted-foreground tabular-nums md:block md:pt-0">{i + 1}</span>
          <div className="font-semibold text-foreground md:mt-2">{it.title}</div>
          <p className="mt-1 text-sm leading-relaxed text-body">{it.text}</p>
        </li>
      ))}
    </ol>
  );
}

export interface RowItem {
  term: ReactNode;
  /** 词下面的小字（价格这类） */
  meta?: ReactNode;
  children: ReactNode;
}

export function Rows({ items, className }: { items: RowItem[]; className?: string }) {
  return (
    <dl className={cn("max-w-3xl", className)}>
      {items.map((it, i) => (
        <div key={i} className="grid gap-1 border-t py-4 first:border-t-0 first:pt-0 sm:grid-cols-[8.5rem_minmax(0,1fr)] sm:gap-x-8">
          <dt className="font-semibold text-foreground">
            {it.term}
            {it.meta ? <span className="ml-2 font-normal text-body tabular-nums sm:ml-0 sm:block">{it.meta}</span> : null}
          </dt>
          <dd className="min-w-0 leading-relaxed">{it.children}</dd>
        </div>
      ))}
    </dl>
  );
}

/** 带 01 编号的条目；lead 是开头加粗的短语（可空） */
export function ListNum({ items }: { items: { lead?: string; text: ReactNode }[] }) {
  return (
    <ol className="max-w-2xl">
      {items.map((it, i) => (
        <li key={i} className="grid grid-cols-[2.25rem_minmax(0,1fr)] border-t py-4 first:border-t-0 first:pt-0">
          <span aria-hidden className="pt-0.5 text-sm text-muted-foreground tabular-nums">{String(i + 1).padStart(2, "0")}</span>
          <p className="leading-relaxed">
            {it.lead ? <strong className="font-semibold text-foreground">{it.lead}</strong> : null}
            {it.text}
          </p>
        </li>
      ))}
    </ol>
  );
}

export function NextLinks({ items }: { items: { q: string; to: string; label: string }[] }) {
  return (
    <div className="mx-auto max-w-6xl px-4 sm:px-6">
      <ul className="flex flex-wrap gap-x-12 gap-y-4 border-t pt-10 pb-16">
        {items.map((it) => (
          <li key={it.to}>
            <Link to={it.to} className="group block">
              <span className="block text-sm text-muted-foreground">{it.q}</span>
              <span className="inline-flex items-center gap-1 font-medium text-primary group-hover:underline">
                {it.label}
                <ArrowRight aria-hidden className="size-4 transition-transform group-hover:translate-x-0.5" />
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** 版心：max-w-6xl + 两边留白（手机 16px、宽屏 24px） */
export function Container({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cn("mx-auto max-w-6xl px-4 sm:px-6", className)}>{children}</div>;
}
