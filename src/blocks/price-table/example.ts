import { defineBlockDemo } from "@/lib/blocks";
import type { ShopBand, ShopTier } from "@/lib/shop-types";

import { PriceTable } from "./PriceTable";

// 示例数据照 11-18 的现价（真页面从 /api/shop/catalog 读，不写死）
const bands: ShopBand[] = [
  { key: "p1", name: "1 篇", max_papers: 1 },
  { key: "p2_3", name: "2–3 篇", max_papers: 3 },
  { key: "p4_5", name: "4–5 篇", max_papers: 5 },
];
const tiers: ShopTier[] = [
  { key: "light", name: "轻量", min_minutes: 1, max_minutes: 15, max_pages: 20, std_hours: 4, rush_hours: 2, rush: true, prices: { p1: "24.9", p2_3: "34.9", p4_5: null } },
  { key: "regular", name: "常规", min_minutes: 16, max_minutes: 25, max_pages: 30, std_hours: 5, rush_hours: 3, rush: true, prices: { p1: "29.9", p2_3: "39.9", p4_5: "49.9" } },
  { key: "long", name: "长", min_minutes: 26, max_minutes: 40, max_pages: 45, std_hours: 8, rush_hours: null, rush: false, prices: { p1: "44.9", p2_3: "54.9", p4_5: "64.9" } },
  { key: "xlong", name: "超长", min_minutes: 41, max_minutes: 60, max_pages: 60, std_hours: 12, rush_hours: null, rush: false, prices: { p1: "59.9", p2_3: "69.9", p4_5: "79.9" } },
];

export default defineBlockDemo({
  block: "price-table",
  title: "价目表（手机上一档一块）",
  order: 8,
  component: PriceTable,
  examples: [{ name: "现价", props: { tiers, bands } }],
});
