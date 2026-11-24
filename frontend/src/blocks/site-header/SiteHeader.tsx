import type { ReactNode } from "react";

import { SiteLink } from "@/components/site-link";
import { cn } from "@/lib/utils";

export interface NavLink {
  label: string;
  href: string;
}

export interface SiteHeaderProps {
  /** 站名（宋体 + 红色句号，和官网、下单页同一个样子）和点了回到哪 */
  brand?: { name: string; href: string };
  /** 这一块自己的导航（官网：价目、下单……；图库：找图、提需求、投图） */
  nav?: NavLink[];
  /** 现在在哪一页（和 nav 里的 href 比），加 aria-current */
  current?: string;
  /** 放在导航后面的几个按钮（图库：「要全部图库？」） */
  actions?: ReactNode;
  /** 最右边的导流入口（图库：「做汇报 PPT 看这里」→ 官网）；点了先记一下 */
  cta?: { text: string; href: string; onClick?: () => void };
}

const linkClass = "whitespace-nowrap text-muted-foreground transition-colors hover:text-foreground";

/**
 * 官网、下单页、兑换页、图库共用的页头（统一站点，模块 L）：细底线、站名宋体加红点、右边灰字导航。
 * 手机上导航换到第二行，站名和导流入口留在第一行。
 */
export function SiteHeader({
  brand = { name: "心理学科研图库", href: "/" },
  nav = [],
  current,
  actions,
  cta,
}: SiteHeaderProps) {
  const links = nav.map((n) => (
    <SiteLink
      key={n.href}
      href={n.href}
      aria-current={current && (current === n.href || current === n.label) ? "page" : undefined}
      className={cn(linkClass, "aria-[current=page]:text-foreground")}
    >
      {n.label}
    </SiteLink>
  ));
  const ctaLink = cta ? (
    <SiteLink href={cta.href} onClick={cta.onClick} className="font-medium whitespace-nowrap text-primary hover:text-primary-hover">
      {cta.text}
    </SiteLink>
  ) : null;
  return (
    <header className="border-b bg-background">
      <div className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-4 px-4 sm:px-6">
        <SiteLink
          href={brand.href}
          className="flex shrink-0 items-baseline font-display text-base font-bold tracking-wide text-foreground sm:text-lg"
        >
          {brand.name}
          <span aria-hidden className="ml-0.5 inline-block size-1.5 rounded-full bg-brand-dot" />
        </SiteLink>
        <nav className="hidden min-w-0 items-center gap-5 text-sm sm:flex" aria-label="主导航">
          {links}
          {actions}
          {ctaLink}
        </nav>
        <div className="text-[13px] sm:hidden">{ctaLink}</div>
      </div>
      {links.length > 0 || actions ? (
        <nav className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-5 gap-y-1 px-4 pb-2.5 text-[13px] sm:hidden" aria-label="主导航">
          {links}
          {actions}
        </nav>
      ) : null}
    </header>
  );
}
