import { defineBlockDemo } from "@/lib/blocks";

import { SiteFooter } from "./SiteFooter";

export default defineBlockDemo({
  block: "site-footer",
  title: "站点页脚",
  order: 999,
  component: SiteFooter,
  examples: [
    {
      name: "统一站点",
      props: {
        company: "杭州竹涧云科技有限公司",
        creditCode: "91330110MAKFUNHCXY",
        icp: "浙ICP备2026046510号-1",
        note: "图片版权归原作者和期刊，仅供学习参考。",
        groups: [
          {
            key: "ppt",
            title: "汇报 PPT 定制",
            items: [
              { label: "价目", href: "https://www.example.org/price.html" },
              { label: "下单", href: "/order" },
              { label: "交付说明", href: "https://www.example.org/service.html" },
              { label: "退款与售后", href: "https://www.example.org/refund.html" },
              { label: "关于我们", href: "https://www.example.org/about.html" },
            ],
          },
          {
            key: "figures",
            title: "心理学科研图库",
            items: [
              { label: "找图", href: "/" },
              { label: "提需求", href: "/request" },
              { label: "投图", href: "/submit" },
            ],
          },
          {
            key: "more",
            title: "更多",
            items: [
              { label: "兑换激活码", href: "/c" },
              { label: "把图库装进你的 AI", href: "/plugin" },
              { label: "版权问题", href: "/copyright" },
            ],
          },
        ],
      },
    },
    { name: "只有公司", props: { company: "杭州竹涧云科技有限公司", icp: "浙ICP备2026046510号-1" } },
  ],
});
