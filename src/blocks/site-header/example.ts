import { defineBlockDemo } from "@/lib/blocks";

import { SiteHeader } from "./SiteHeader";

export default defineBlockDemo({
  block: "site-header",
  title: "站点页头",
  order: 0,
  component: SiteHeader,
  examples: [
    {
      name: "图库",
      props: {
        brand: { name: "心理学科研图库", href: "/" },
        nav: [
          { label: "找图", href: "/" },
          { label: "提需求", href: "/request" },
          { label: "投图", href: "/submit" },
        ],
        current: "/",
        cta: { text: "做汇报 PPT 看这里", href: "https://www.example.org/" },
      },
    },
    {
      name: "官网、下单页",
      props: {
        brand: { name: "心理学汇报 PPT 定制", href: "https://www.example.org/" },
        nav: [
          { label: "价目", href: "https://www.example.org/price.html" },
          { label: "下单", href: "/order" },
          { label: "交付说明", href: "https://www.example.org/service.html" },
          { label: "退款与售后", href: "https://www.example.org/refund.html" },
          { label: "关于我们", href: "https://www.example.org/about.html" },
        ],
        current: "/order",
      },
    },
  ],
});
