import { createElement } from "react";

import { defineBlockDemo } from "@/lib/blocks";
import type { SiteConfig } from "@/lib/website-types";

import { FlowShell } from "./FlowShell";

const site = {
  company_name: "杭州竹涧云科技有限公司", credit_code: "91330110MAKFUNHCXY", icp: "浙ICP备2026046510号-1",
  icp_url: "https://beian.miit.gov.cn/", police_beian: "", police_beian_url: "", phone: "", phone_note: "", email: "",
} as unknown as SiteConfig;

export default defineBlockDemo({
  block: "flow-shell",
  title: "流程页外框：精简页脚",
  order: 63,
  component: FlowShell,
  examples: [
    { name: "需求卡、兑换页用", props: { site, children: createElement("p", { className: "px-4 py-10 text-sm" }, "这里是页面正文") } },
    { name: "设置还没取到", props: { site: null, children: createElement("p", { className: "px-4 py-10 text-sm" }, "这里是页面正文") } },
  ],
});
