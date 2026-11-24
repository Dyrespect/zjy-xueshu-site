import { createElement } from "react";

import { SlideViewer } from "@/blocks/site-home";
import { defineBlockDemo } from "@/lib/blocks";
import { MEDIA } from "@/lib/site-media";

import { Hero } from "./SiteHero";

export default defineBlockDemo({
  block: "site-hero",
  title: "官网首屏（主张、两个按钮、起价、看稿器）",
  order: 7,
  component: Hero,
  examples: [
    {
      name: "默认",
      props: {
        eyebrow: "组会 · 开题 · 中期 · 答辩 · 会议报告",
        title: "让汇报不再|卡在 PPT 上",
        lead: "一顿外卖钱起，一份专业的心理学汇报 PPT。",
        text: "面向心理学研究生和博士生。你发来论文或材料，我们按你的汇报时长做好。",
        actions: createElement("a", { href: "#", className: "inline-flex h-11 items-center justify-center rounded-md bg-primary px-6 text-sm font-medium text-primary-foreground" }, "去下单"),
        meta: createElement("span", null, createElement("span", { className: "text-base font-semibold text-price" }, "24.9"), " 元起，按汇报时长和材料篇数定价，下单前都写清楚。"),
        stage: createElement(SlideViewer, {
          slides: [
            { media: MEDIA.p01, label: "第 3 页 · 研究思路与技术路线" },
            { media: MEDIA.p02, label: "第 5 页 · 研究一：开盒找证据的实验" },
          ],
          caption: "示范稿 · 中期汇报",
        }),
      },
    },
  ],
});
