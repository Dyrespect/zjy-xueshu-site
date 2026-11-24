import { defineBlockDemo } from "@/lib/blocks";

import { PopularChips } from "./PopularChips";

const chips = [
  "假设模型", "中介和调节", "实验流程", "试次流程", "技术路线", "研究框架", "被试筛选流程", "测量时间线", "结果图·交互作用", "网络图",
].map((label) => ({ label, query: label === "结果图·交互作用" ? "交互作用" : label }));

export default defineBlockDemo({
  block: "popular-chips",
  title: "常见要画的",
  order: 11,
  component: PopularChips,
  examples: [{ name: "默认", props: { chips, hrefFor: (c) => `/search?q=${encodeURIComponent(c.query)}` } }],
});
