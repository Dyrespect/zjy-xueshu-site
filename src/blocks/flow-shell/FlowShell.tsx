import type { ReactNode } from "react";
import { Link } from "react-router";

import { SiteHeaderBar } from "@/blocks/site-shell";
import { LICENSE_PATH, sitePage } from "@/lib/site-pages";
import type { SiteConfig } from "@/lib/website-types";
import { cn } from "@/lib/utils";

/**
 * 客人「在走流程」的页面（兑换页 /c、需求卡 /b）用的外框：页头跟全站同一个（blocks/site-shell 的 SiteHeaderBar，不改它），
 * 页脚换成精简的一行——公司全称、ICP 备案号、用户协议、隐私政策（主体信息照样从后台「官网」设置读）。
 * 全站页脚四栏链接在手机上占半屏，客人一步一步点的时候是干扰。
 */

const LEGAL = ["/terms", "/privacy"] as const;

export interface FlowFooterProps {
  /** 主体信息（/api/website/config）；还没取到时只有两个协议链接 */
  site: SiteConfig | null;
}

export function FlowFooter({ site }: FlowFooterProps) {
  return (
    <footer className="border-t bg-background">
      <div
        className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-3 gap-y-1 px-4 py-5 text-xs leading-relaxed text-muted-foreground sm:px-6"
        data-testid="site-legal"
      >
        {site ? (
          <>
            <span>{site.company_name}</span>
            <a href={site.icp_url} target="_blank" rel="noopener noreferrer" className="hover:text-foreground">
              {site.icp}
            </a>
            <Link to={LICENSE_PATH} className="hover:text-foreground" data-testid="footer-license">
              营业执照
            </Link>
          </>
        ) : null}
        {LEGAL.map((path) => (
          <Link key={path} to={path} className="hover:text-foreground">
            {sitePage(path)?.title ?? path}
          </Link>
        ))}
      </div>
    </footer>
  );
}

export interface FlowShellProps {
  site: SiteConfig | null;
  children?: ReactNode;
  /** 显示页头的「下单」按钮（流程里的页一般不要） */
  cta?: boolean;
  className?: string;
}

/** 页头 + 正文 + 精简页脚。只吃 props；要自己取设置的用 load.tsx 里的 FlowFrame。 */
export function FlowShell({ site, children, cta = false, className }: FlowShellProps) {
  return (
    <div className={cn("flex min-h-dvh flex-col bg-background text-body", className)}>
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-background focus:px-3 focus:py-2 focus:text-foreground">
        跳到正文
      </a>
      <SiteHeaderBar cta={cta} />
      <main id="main" className="flex-1">
        {children}
      </main>
      <FlowFooter site={site} />
    </div>
  );
}
