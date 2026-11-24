import { defineBlockDemo } from "@/lib/blocks";

import { FigureSearchBox } from "./FigureSearchBox";

export default defineBlockDemo({
  block: "figure-search-box",
  title: "找图搜索框",
  order: 10,
  component: FigureSearchBox,
  examples: [
    { name: "首页大框", props: { onSubmit: () => undefined } },
    { name: "结果页顶上", props: { size: "compact", defaultValue: "被试内实验的试次流程", onSubmit: () => undefined } },
  ],
});
