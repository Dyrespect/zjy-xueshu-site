import { getShopCatalog, type ShopCatalog } from "@/lib/shop";

let cached: Promise<ShopCatalog> | null = null;

/** 价目（下单页要整份）。一个页面会话里只取一次。 */
export function loadCatalog(force = false): Promise<ShopCatalog> {
  if (!cached || force) {
    cached = getShopCatalog().catch((e) => {
      cached = null;
      throw e;
    });
  }
  return cached;
}
