import { createElement, Fragment } from "react";

import { defineBlockDemo } from "@/lib/blocks";

import { ListNum, More, Rows, Section, Steps } from "./SiteSection";

const h = createElement;

function Demo() {
  return h(
    "div",
    { className: "mx-auto max-w-6xl px-4 sm:px-6" },
    h(
      Section,
      { title: "怎么交", no: "01" },
      h(Steps, {
        items: [
          { title: "先交水印版", text: "每页一张完整大小的图片，铺了水印，用来看效果、提修改。" },
          { title: "含 1 轮修改", text: "看完把要改的地方一次说齐，我们改好再交一版。" },
          { title: "确认收货", text: "你点「确认收货」后，我们发可编辑的 PPT 和讲稿。" },
        ],
      }),
      h(More, { to: "/service" }, "完整交付说明"),
    ),
    h(
      Section,
      { title: "退款与售后" },
      h(Rows, {
        items: [
          { term: "开工前", children: "开工前想撤单，可以退款。" },
          { term: "开始制作后", children: "开始制作后不支持仅退款。不满意，先告诉我们哪里要改。" },
        ],
      }),
    ),
    h(
      Section,
      { title: "注意事项" },
      h(ListNum, {
        items: [
          { lead: "先认领，再交材料：", text: "付款后用激活码认领订单，再上传材料。" },
          { lead: "时间：", text: "从开工算，在这一档的标准时限内交水印版。" },
        ],
      }),
    ),
  );
}

export default defineBlockDemo({
  block: "site-section",
  title: "官网版面零件（小节、步骤、左右两列、编号条目）",
  order: 6,
  component: () => h(Fragment, null, h(Demo)),
  examples: [{ name: "三种小节", props: {} }],
});
