import { useEffect, useState } from "react";

import { getShopCatalog, type ShopCatalog } from "@/lib/shop";

let cached: Promise<ShopCatalog> | null = null;

/** 价目（/api/shop/catalog，背后是订单中枢的 sku.catalog）。官网几页共用一份，一个页面会话只取一次。 */
export function useCatalog(): { catalog: ShopCatalog | null; error: string } {
  const [catalog, setCatalog] = useState<ShopCatalog | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    if (!cached) {
      cached = getShopCatalog().catch((e) => {
        cached = null;
        throw e;
      });
    }
    cached
      .then((c) => alive && setCatalog(c))
      .catch((e) => alive && setError(e instanceof Error ? e.message : "价目没取到"));
    return () => {
      alive = false;
    };
  }, []);
  return { catalog, error };
}
