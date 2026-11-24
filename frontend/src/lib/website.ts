/**
 * 官网：页脚和联系方式的设置（/api/website/config）、后台「官网」页。下单前的同意随单带给 /api/shop/checkout（lib/shop.ts）。
 * 只通过 api.ts 发请求。
 */
import { api, apiGet } from "./api";
import type { ConsentRow, SiteConfig, WebsiteConfigFull, WebsiteSettingsData } from "./website-types";

export * from "./website-types";

let cached: Promise<SiteConfig> | null = null;

/** 一个页面会话里只取一次（页头页脚每页都要，不重复请求）；失败了下次再取 */
export function getSiteConfig(force = false): Promise<SiteConfig> {
  if (!cached || force) {
    cached = apiGet<SiteConfig>("/website/config").catch((e) => {
      cached = null;
      throw e;
    });
  }
  return cached;
}

/** 运行状态页：后端和数据库通不通（/api/health；更细的服务状态由运维那边接入后换成它的接口） */
export const getHealth = () => apiGet<{ status: string; db: string }>("/health");


// ---------------- 后台 ----------------

export const getWebsiteSettings = () => apiGet<WebsiteSettingsData>("/admin/website/settings");
export const saveWebsiteSettings = (config: WebsiteConfigFull) =>
  api<WebsiteSettingsData>("/admin/website/settings", { method: "PUT", json: { config } }).then((r) => {
    cached = null; // 页脚马上用新的
    return r;
  });
export const listConsents = () => apiGet<{ rows: ConsentRow[] }>("/admin/website/consents");
