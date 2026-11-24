import type { ShopBand, ShopTier } from "@/lib/shop-types";
import { cn } from "@/lib/utils";

/**
 * 价目表（psyppt静态站 price_table）和首页的四档起价（tiers）。数字全是 props（页面从 /api/shop/catalog 拿，
 * 背后是订单中枢的 sku.catalog），这里不写一个价。手机上一档变成一块（表头藏起来，每格前面带小标签）。
 */

export interface PriceTableProps {
  tiers: ShopTier[];
  bands: ShopBand[];
}

const NA = "不开放";

function Na() {
  return <span className="text-sm text-muted-foreground">{NA}</span>;
}

export function PriceTable({ tiers, bands }: PriceTableProps) {
  const cell = "border-b py-4 pr-4 align-baseline max-sm:border-0 max-sm:p-0";
  const label = "max-sm:before:block max-sm:before:text-xs max-sm:before:font-normal max-sm:before:text-muted-foreground max-sm:before:content-[attr(data-label)]";
  return (
    <div className="mt-2">
      <table className="w-full border-collapse text-left max-sm:block">
        <caption className="sr-only">价目表：按汇报时长选档，按材料篇数定价，单位人民币元</caption>
        <thead className="max-sm:sr-only">
          <tr className="text-xs font-medium whitespace-nowrap text-muted-foreground">
            <th scope="col" rowSpan={2} className="border-b py-2 pr-4 align-bottom font-medium">档 · 汇报时长</th>
            <th scope="col" rowSpan={2} className="border-b py-2 pr-4 align-bottom font-medium">内容页上限</th>
            <th scope="colgroup" colSpan={bands.length} className="border-b border-b-faint py-2 pr-4 font-medium">价格（元）</th>
            <th scope="colgroup" colSpan={2} className="border-b border-b-faint py-2 pr-4 font-medium">交水印版</th>
          </tr>
          <tr className="text-xs whitespace-nowrap text-muted-foreground">
            {bands.map((b, i) => (
              <th key={b.key} scope="col" className="border-b py-2 pr-4 font-medium">{i === 0 ? `${b.name}材料` : b.name}</th>
            ))}
            <th scope="col" className="border-b py-2 pr-4 font-medium">标准</th>
            <th scope="col" className="border-b py-2 pr-4 font-medium">加急</th>
          </tr>
        </thead>
        <tbody className="max-sm:block">
          {tiers.map((t) => (
            <tr key={t.key} className="max-sm:grid max-sm:grid-cols-6 max-sm:gap-3 max-sm:border-b max-sm:py-5">
              <th scope="row" className={cn(cell, "text-foreground max-sm:col-span-6 max-sm:flex max-sm:items-baseline max-sm:gap-3")}>
                <span className="block font-semibold">{t.name}</span>
                <span className="block text-sm font-normal text-muted-foreground tabular-nums">
                  {t.min_minutes <= 1 ? `${t.max_minutes} 分钟以内` : `${t.min_minutes}–${t.max_minutes} 分钟`}
                </span>
              </th>
              <td data-label="内容页上限" className={cn(cell, "whitespace-nowrap tabular-nums max-sm:col-span-6 max-sm:flex max-sm:gap-2 max-sm:text-sm max-sm:before:inline max-sm:before:text-xs max-sm:before:text-muted-foreground max-sm:before:content-[attr(data-label)]")}>
                {t.max_pages} 页
              </td>
              {bands.map((b) => {
                const p = t.prices[b.key];
                return (
                  <td key={b.key} data-label={b.name} className={cn(cell, label, "whitespace-nowrap tabular-nums max-sm:col-span-2")}>
                    {p ? <span className="text-lg font-semibold text-foreground">{p}</span> : <Na />}
                  </td>
                );
              })}
              <td data-label="标准交水印版" className={cn(cell, label, "whitespace-nowrap tabular-nums max-sm:col-span-3 max-sm:text-sm")}>
                {t.std_hours} 小时
              </td>
              <td data-label="加急交水印版" className={cn(cell, label, "whitespace-nowrap tabular-nums max-sm:col-span-3 max-sm:text-sm")}>
                {t.rush && t.rush_hours ? `${t.rush_hours} 小时` : <Na />}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** 一档的起价：开放的篇数里最低的那个 */
export function tierFrom(t: ShopTier): string | null {
  const vals = Object.values(t.prices).filter((v): v is string => !!v);
  if (!vals.length) return null;
  return vals.reduce((a, b) => (Number(b) < Number(a) ? b : a));
}

/** 四档起价一排（首页「价目」）：四列等宽、每列顶上一根细线（claude.com、BioRender 定价页的四列）；价格用黑，不用红（一屏红色最多一两处） */
export function Tiers({ tiers }: { tiers: ShopTier[] }) {
  return (
    <ul aria-label="各档起价" className="grid grid-cols-2 gap-x-6 gap-y-10 md:grid-cols-4 md:gap-x-8">
      {tiers.map((t) => {
        const from = tierFrom(t);
        return (
          <li key={t.key} className="border-t border-foreground pt-5">
            <div className="flex items-baseline justify-between gap-3">
              <span className="text-lg font-semibold text-foreground">{t.name}</span>
              <span className="text-sm text-muted-foreground tabular-nums">
                {t.min_minutes <= 1 ? `${t.max_minutes} 分钟以内` : `${t.min_minutes}–${t.max_minutes} 分钟`}
              </span>
            </div>
            <div className="mt-6 text-[clamp(2.25rem,1.8rem+1.6vw,3rem)] leading-none font-semibold tracking-[-0.02em] text-foreground tabular-nums">
              {from ?? NA}
              {from ? <span className="ml-1.5 text-sm font-normal tracking-normal text-muted-foreground">元起</span> : null}
            </div>
            <div className="mt-3 text-sm text-muted-foreground tabular-nums">
              内容页不超过 {t.max_pages} 页 · {t.std_hours} 小时交水印版
            </div>
          </li>
        );
      })}
    </ul>
  );
}
