import { createContext, useContext, useEffect } from "react";

import type { SearchContext, SiteInfo } from "@/lib/figures-types";
import type { CtaPlacement, SiteMap } from "@/lib/site-types";

export interface GalleryContextValue {
  site: SiteInfo | null;
  /** 统一站点地图（页头页脚、导流入口、插件名字、公众号） */
  map: SiteMap | null;
  /** 打开提需求弹层（带上刚才搜的话） */
  openRequest: (ctx?: SearchContext) => void;
  openAllLibrary: () => void;
  /** 记一次「做汇报 PPT」这类入口的点击（整页跳走前发出去） */
  trackCta: (placement: CtaPlacement, target: "site" | "order") => void;
}

export const GalleryContext = createContext<GalleryContextValue>({
  site: null,
  map: null,
  openRequest: () => undefined,
  openAllLibrary: () => undefined,
  trackCta: () => undefined,
});

export const useGallery = () => useContext(GalleryContext);

const SITE = "心理学科研图库";

export function useTitle(title?: string) {
  useEffect(() => {
    document.title = title ? `${title} - ${SITE}` : `${SITE}：心理学好刊里的图，按你要画的找`;
  }, [title]);
}

export const searchHref = (q: string, code?: string | null) =>
  `/search?q=${encodeURIComponent(q)}${code ? `&code=${encodeURIComponent(code)}` : ""}`;
export const figureHref = (id: number) => `/figure/${id}`;
export const typeHref = (code: string) => `/types/${code}`;

/** 去下单页的地址换个位置（站点地图里是 from=tuku_nav）：算得出是页头、结果页还是领完图库点过去的。 */
export function orderHref(map: SiteMap | null, placement: CtaPlacement): string {
  const base = map?.cta.order_url ?? "/order?from=tuku_nav";
  return base.replace(/from=tuku_[a-z_]+/, `from=tuku_${placement}`);
}
