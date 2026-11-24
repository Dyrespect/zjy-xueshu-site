import { createElement } from "react";

import { defineBlockDemo } from "@/lib/blocks";
import type { SiteConfig } from "@/lib/website-types";

import { SiteShell } from "./SiteShell";

const site: SiteConfig = {
  company_name: "杭州竹涧云科技有限公司",
  credit_code: "91330110MAKFUNHCXY",
  icp: "浙ICP备2026046510号-1",
  icp_url: "https://beian.miit.gov.cn/",
  police_beian: "",
  police_beian_url: "",
  phone: "15068998671",
  phone_note: "微信同号",
  email: "",
  address: "",
  service_hours: "",
  reply_promise: "一般 1 个工作日内答复",
  indexable: false,
  maintenance: false,
  maintenance_text: "网站正在维护，预计很快恢复。如有急事，请拨打客服电话。",
};

const body = createElement("div", { className: "mx-auto max-w-6xl px-4 py-16 text-sm text-muted-foreground sm:px-6" }, "（页面内容）");

export default defineBlockDemo({
  block: "site-shell",
  title: "全站页头页脚（官网、下单、付款、交付共用）",
  order: 5,
  component: SiteShell,
  examples: [
    { name: "官网内页（当前页：价目）", props: { site, current: "/price", children: body } },
    {
      name: "填了公安备案号和邮箱",
      props: { site: { ...site, police_beian: "浙公网安备33010002000001号", police_beian_url: "https://beian.mps.gov.cn/#/query/webSearch?code=33010002000001", email: "kefu@example.com" }, children: body },
    },
    { name: "交付页（不放下单按钮，右边放单号）", props: { site, cta: false, aside: createElement("span", { className: "text-sm text-muted-foreground tabular-nums" }, "单号 W26111800012"), children: body } },
  ],
});
