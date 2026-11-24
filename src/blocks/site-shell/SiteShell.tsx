import type { ReactNode } from "react";
import { Link } from "react-router";

import { Button } from "@/components/ui/button";
import { LICENSE_PATH, MAIN_NAV, ORDER_PATH, SITE_GROUPS, SITE_NAME, SITE_PAGES, sitePage } from "@/lib/site-pages";
import type { SiteConfig } from "@/lib/website-types";
import { cn } from "@/lib/utils";

/**
 * 全站同一套页头页脚（官网各页、下单页、付款页、交付页、出错页都用它；图库换过来也用它）。
 * 样子照 psyppt 官网（psyppt静态站/设计说明.md 第三节 site_header / site_footer）：
 * 宋体站名 + 红色句号；右边一排灰字导航，当前页加粗加底线；「下单」是唯一的实心按钮。
 * 页脚：公司全称、统一社会信用代码、ICP 备案号、公安备案号（填了才显示）、联系电话，右边三组链接。主体信息全来自设置（props.site）。
 */

export interface SiteHeaderBarProps {
  /** 当前页路径（导航里标出来） */
  current?: string;
  /** 「下单」按钮左边加的东西（交付页放单号） */
  aside?: ReactNode;
  /** 显示「下单」按钮（交付页、下单页自己不显示） */
  cta?: boolean;
  /** 桌面上滚动时页头钉在顶上（官网各页要；下单页、交付页不要，免得碰它们自己的粘性汇总） */
  sticky?: boolean;
}

export function Wordmark({ current }: { current?: string }) {
  return (
    <Link
      to="/"
      aria-current={current === "/" ? "page" : undefined}
      className="inline-flex shrink-0 items-baseline font-headline text-base font-semibold tracking-wide whitespace-nowrap text-foreground sm:text-lg"
    >
      {SITE_NAME}
      <span aria-hidden className="ml-[0.14em] inline-block size-[0.3em] rounded-full bg-brand-dot" />
    </Link>
  );
}

export function SiteHeaderBar({ current, aside, cta = true, sticky = false }: SiteHeaderBarProps) {
  return (
    <header className={cn("border-b bg-background", sticky && "md:sticky md:top-0 md:z-40")}>
      <div className="mx-auto flex min-h-14 max-w-6xl flex-wrap items-center justify-between gap-x-8 px-4 pt-3 sm:px-6 md:flex-nowrap md:pt-0">
        <Wordmark current={current} />
        <div className="flex items-center gap-3 md:order-last">
          {aside}
          {cta ? (
            <Button asChild size="sm" className="px-4">
              <Link to={ORDER_PATH}>下单</Link>
            </Button>
          ) : null}
        </div>
        {/* 手机上一行横滑（不折成两行、不撑宽页面），宽屏放在右边 */}
        <nav
          aria-label="主导航"
          className="-mx-4 flex w-[calc(100%+2rem)] gap-x-5 overflow-x-auto px-4 text-[13px] [scrollbar-width:none] sm:mx-0 sm:w-full sm:gap-x-6 sm:px-0 sm:text-sm md:ml-auto md:w-auto md:overflow-visible [&::-webkit-scrollbar]:hidden"
        >
          {MAIN_NAV.map((path) => {
            const p = sitePage(path);
            const on = current === path;
            return (
              <Link
                key={path}
                to={path}
                aria-current={on ? "page" : undefined}
                className={cn(
                  "flex min-h-11 items-center whitespace-nowrap transition-colors md:min-h-14",
                  on ? "font-medium text-foreground shadow-[inset_0_-2px_0_currentColor]" : "text-muted-foreground hover:text-foreground",
                )}
              >
                {p?.title ?? path}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}

export interface SiteFooterBarProps {
  /** 主体信息和联系方式（/api/website/config）；还没取到时页脚只有链接 */
  site: SiteConfig | null;
}

const footLink = "text-muted-foreground transition-colors hover:text-foreground";

export function SiteFooterBar({ site }: SiteFooterBarProps) {
  const year = new Date().getFullYear();
  return (
    <footer className="border-t bg-background">
      <div className="mx-auto grid max-w-6xl gap-8 px-4 pt-10 pb-12 text-sm sm:px-6 lg:grid-cols-[minmax(0,1fr)_auto] lg:gap-16">
        <div data-testid="site-legal">
          {site ? (
            <>
              <div className="flex items-center gap-2 font-medium text-foreground">
                <span
                  aria-hidden
                  className="size-5 flex-none bg-current"
                  style={{ WebkitMask: "url(/site-assets/zhujianyun.svg) center / contain no-repeat", mask: "url(/site-assets/zhujianyun.svg) center / contain no-repeat" }}
                />
                {site.company_name}
              </div>
              <p className="mt-3 text-xs leading-loose text-muted-foreground">
                <span className="block">
                  统一社会信用代码 <span className="tabular-nums">{site.credit_code}</span>
                  <span aria-hidden className="mx-2">·</span>
                  <Link to={LICENSE_PATH} className="underline underline-offset-2 hover:text-foreground" data-testid="footer-license">
                    营业执照
                  </Link>
                </span>
                <span className="block">
                  <a href={site.icp_url} target="_blank" rel="noopener noreferrer" className="hover:text-foreground">
                    {site.icp}
                  </a>
                  {site.police_beian ? (
                    <>
                      <span aria-hidden className="mx-2">·</span>
                      <a href={site.police_beian_url} target="_blank" rel="noopener noreferrer" className="hover:text-foreground">
                        {site.police_beian}
                      </a>
                    </>
                  ) : null}
                </span>
                {site.phone ? (
                  <span className="block">
                    联系电话 <a href={`tel:${site.phone.replace(/[\s-]/g, "")}`} className="tabular-nums hover:text-foreground">{site.phone}</a>
                    {site.phone_note ? `（${site.phone_note}）` : ""}
                    {site.email ? (
                      <>
                        <span aria-hidden className="mx-2">·</span>
                        <a href={`mailto:${site.email}`} className="hover:text-foreground">{site.email}</a>
                      </>
                    ) : null}
                  </span>
                ) : null}
                <span className="block">© {year} {site.company_name}</span>
              </p>
            </>
          ) : (
            <div className="h-24" aria-hidden />
          )}
        </div>
        <nav aria-label="页脚导航" className="grid grid-cols-2 gap-x-6 gap-y-8 sm:grid-cols-4 sm:gap-x-12">
          {SITE_GROUPS.map((g) => (
            <div key={g} className="flex flex-col gap-2">
              <span className="text-xs text-muted-foreground">{g}</span>
              {SITE_PAGES.filter((p) => p.group === g && p.path !== "/").map((p) => (
                <Link key={p.path} to={p.path} className={cn(footLink, "whitespace-nowrap")}>
                  {p.title}
                </Link>
              ))}
            </div>
          ))}
        </nav>
      </div>
    </footer>
  );
}

export interface SiteShellProps extends SiteHeaderBarProps {
  site: SiteConfig | null;
  children?: ReactNode;
  /** 正文外面加不加 text-base（官网正文 16px；后台那种密的页面不要） */
  className?: string;
}

/** 页头 + 正文 + 页脚。只吃 props；要自己取设置的用 load.tsx 里的 SiteFrame。 */
export function SiteShell({ site, current, aside, cta, sticky, children, className }: SiteShellProps) {
  return (
    <div className={cn("flex min-h-dvh flex-col bg-background text-body", className)}>
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-background focus:px-3 focus:py-2 focus:text-foreground">
        跳到正文
      </a>
      <SiteHeaderBar current={current} aside={aside} cta={cta} sticky={sticky} />
      <main id="main" className="flex-1">
        {children}
      </main>
      <SiteFooterBar site={site} />
    </div>
  );
}

export interface StatusViewProps {
  /** 小字，如 404、500 */
  code?: string;
  title: string;
  text: ReactNode;
  actions?: ReactNode;
  /** 右边一张图（404 放一张空白幻灯片，页码写 404） */
  aside?: ReactNode;
}

/** 404、出错、维护中这类「这一页只说一件事」的正文。 */
export function StatusView({ code, title, text, actions, aside }: StatusViewProps) {
  return (
    <section className={cn("mx-auto flex min-h-[55vh] max-w-6xl flex-col justify-center px-4 py-16 sm:px-6", aside && "md:grid md:grid-cols-[minmax(0,5fr)_minmax(0,6fr)] md:items-center md:gap-16")}>
      <div>
        {code ? <span className="text-sm text-muted-foreground tabular-nums">{code}</span> : null}
        <h1 className="mt-2 font-headline text-headline font-semibold tracking-[-0.01em] text-foreground">{title}</h1>
        <div className="mt-4 max-w-2xl text-base leading-relaxed text-body">{text}</div>
        {actions ? <div className="mt-8 flex flex-wrap gap-3">{actions}</div> : null}
      </div>
      {aside ? <div className="mt-12 md:mt-0">{aside}</div> : null}
    </section>
  );
}

/** 一张空白幻灯片（CSS 画的，不用图）：标题线、几行占位线，右下角页码。404 页用，页码写 404 */
export function BlankSlide({ page }: { page: string }) {
  return (
    <div aria-hidden className="rounded-xl bg-card p-[clamp(0.75rem,3vw,2rem)]">
      <div className="relative aspect-[16/9] rounded-sm bg-background p-[6%] shadow-figure outline outline-1 -outline-offset-1 outline-border">
        <div className="h-[7%] w-[46%] rounded-[2px] bg-border" />
        <div className="mt-[3%] h-px w-full bg-border" />
        <div className="mt-[7%] grid grid-cols-[3fr_2fr] gap-[6%]">
          <div className="flex flex-col gap-[0.9em] text-[clamp(6px,0.9vw,10px)]">
            <div className="h-[0.9em] w-full rounded-[2px] bg-accent" />
            <div className="h-[0.9em] w-[86%] rounded-[2px] bg-accent" />
            <div className="h-[0.9em] w-[92%] rounded-[2px] bg-accent" />
            <div className="h-[0.9em] w-[64%] rounded-[2px] bg-accent" />
          </div>
          <div className="aspect-[4/3] rounded-[2px] border border-dashed border-border" />
        </div>
        <span className="absolute right-[4%] bottom-[5%] text-[clamp(10px,1.1vw,14px)] text-muted-foreground tabular-nums">{page}</span>
      </div>
    </div>
  );
}
