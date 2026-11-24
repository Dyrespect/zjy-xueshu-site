import { useEffect, useState, type ReactNode } from "react";
import { Link } from "react-router";

import { Button } from "@/components/ui/button";
import { useRobotsMeta } from "@/lib/page-meta";
import { getSiteConfig, type SiteConfig } from "@/lib/website";

import { SiteShell, StatusView, type SiteHeaderBarProps } from "./SiteShell";

/** 页脚要的设置（公司、备案号、电话、开关）。整个页面会话只取一次；取不到返回 null（页脚只剩链接）。 */
export function useSiteConfig(): SiteConfig | null {
  const [site, setSite] = useState<SiteConfig | null>(null);
  useEffect(() => {
    let alive = true;
    getSiteConfig()
      .then((c) => alive && setSite(c))
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);
  return site;
}

export interface SiteFrameProps extends SiteHeaderBarProps {
  children?: ReactNode;
  /** 开了「维护中」时这一页换成维护中（官网各页、下单页要；付款页、交付页不要，客人付到一半、看稿看到一半不能挡） */
  gate?: boolean;
  /** 不管开关，这一页一律不让搜索引擎收（交付页、付款页这类带令牌的页） */
  noindex?: boolean;
  className?: string;
}

/**
 * 自己取设置的外框：页头页脚 + 「公开给搜索引擎」关着时加 noindex + 维护中。
 * 页面用它；只吃 props 的版本是 SiteShell。
 */
export function SiteFrame({ children, gate = true, noindex = false, ...rest }: SiteFrameProps) {
  const site = useSiteConfig();
  useRobotsMeta(noindex ? true : site ? !site.indexable : null);
  const down = gate && site?.maintenance;
  return (
    <SiteShell site={site} {...rest}>
      {down ? (
        <StatusView
          title="网站正在维护"
          text={
            <>
              <p>{site.maintenance_text}</p>
              {site.phone ? (
                <p className="mt-2">
                  客服电话 <a href={`tel:${site.phone}`} className="text-primary underline underline-offset-2 hover:text-primary-hover">{site.phone}</a>
                  {site.phone_note ? `（${site.phone_note}）` : ""}
                </p>
              ) : null}
            </>
          }
          actions={
            <Button variant="outline" asChild>
              <Link to="/contact">联系我们</Link>
            </Button>
          }
        />
      ) : (
        children
      )}
    </SiteShell>
  );
}
