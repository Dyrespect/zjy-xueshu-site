/**
 * 图库单独用一个域名时（科研绘图聚人设计第六节第 7 条），那个域名的站点根 / 要进图库首页（/tuku），不进官网首页。
 * 构建时给 VITE_FIGURES_HOST=<图库域名>（多个用逗号）；不给就只有一个站，/ 永远是官网首页。
 */
export function isFiguresHost(host = typeof window === "undefined" ? "" : window.location.host): boolean {
  const hosts = String(import.meta.env.VITE_FIGURES_HOST ?? "").split(",").map((h) => h.trim()).filter(Boolean);
  return hosts.includes(host);
}
