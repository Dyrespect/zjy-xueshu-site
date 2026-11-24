import { createElement as h } from "react";

import { defineBlockDemo } from "@/lib/blocks";
import { MEDIA } from "@/lib/site-media";

import { Band } from "./Band";
import { Pic } from "./Pic";

function Demo() {
  return h(
    "div",
    null,
    h(Band, { no: "01", eyebrow: "原文到汇报页", title: "原文这样写，我们画成这样。", lead: "论文里是三段英文，组会上要的是一张图。" }, h(Pic, { media: MEDIA.p02 })),
    h(Band, { tone: "inverse", no: "02", eyebrow: "样张", title: "都是我们做的，这里只是一部分。" }),
    h(Band, { no: "03", eyebrow: "占位", title: "还没有图的位置（只在本机开发时显示）" }, h(Pic, { slot: "交付页截图：水印版一页 + 提修改框（R7）", ratio: "16/10" })),
  );
}

export default defineBlockDemo({
  block: "site-home",
  title: "官网首页零件（一屏、图注、图位和占位）",
  order: 8,
  component: Demo,
  examples: [{ name: "三种屏", props: {} }],
});
