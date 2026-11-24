/**
 * 自己取设置的精简外框：页头 + 正文 + 一行页脚（公司、备案号、两个协议）；带令牌的页一律不让搜索引擎收。
 * 设置怎么取跟全站外框一样（blocks/site-shell/load 的 useSiteConfig）。
 */
import type { ReactNode } from "react";

import { useSiteConfig } from "@/blocks/site-shell/load";
import { useRobotsMeta } from "@/lib/page-meta";

import { FlowShell } from "./FlowShell";

export function FlowFrame({ children, noindex = true, className }: { children?: ReactNode; noindex?: boolean; className?: string }) {
  const site = useSiteConfig();
  useRobotsMeta(noindex ? true : null);
  return (
    <FlowShell site={site} className={className}>
      {children}
    </FlowShell>
  );
}
