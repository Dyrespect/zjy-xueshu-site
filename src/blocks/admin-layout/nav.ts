/**
 * 后台侧栏的菜单。「图库」一组的页面由图库那边做（路由 /admin/figures/*），这里只留位置。
 */
export interface NavItem {
  label: string;
  href: string;
  /** 小圆点里的数（比如有几条回复等你批）；0 或不填就不显示 */
  badge?: number;
}

export interface NavGroup {
  title: string;
  items: NavItem[];
}

export const ADMIN_NAV: NavGroup[] = [
  {
    title: "接单",
    items: [
      { label: "会话", href: "/admin/conversations" },
      { label: "订单", href: "/admin/orders" },
      { label: "激活码", href: "/admin/codes" },
      { label: "渠道与收款", href: "/admin/channels" },
      { label: "入口", href: "/admin/entry" },
      { label: "发票", href: "/admin/invoices" },
      { label: "设置", href: "/admin/settings" },
      { label: "官网", href: "/admin/website" },
      { label: "节点目录", href: "/admin/nodes" },
    ],
  },
  {
    title: "网站",
    items: [{ label: "运维", href: "/admin/ops" }],
  },
  {
    title: "图库",
    items: [
      { label: "标签反馈", href: "/admin/figures/feedback" },
      { label: "需求", href: "/admin/figures/requests" },
      { label: "投图", href: "/admin/figures/submissions" },
      { label: "网站意见", href: "/admin/figures/site" },
      { label: "搜索统计", href: "/admin/figures/stats" },
      { label: "聚人（领取、网盘、版权、设置）", href: "/admin/gather" },
    ],
  },
];

export function withBadges(groups: NavGroup[], badges: Record<string, number>): NavGroup[] {
  return groups.map((g) => ({ ...g, items: g.items.map((it) => ({ ...it, badge: badges[it.href] ?? it.badge })) }));
}
