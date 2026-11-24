import { defineBlockDemo } from "@/lib/blocks";

import { FigureTypeIndex } from "./FigureTypeIndex";

export default defineBlockDemo({
  block: "figure-type-index",
  title: "按用途分的图型",
  order: 12,
  component: FigureTypeIndex,
  examples: [
    {
      name: "四组（库里真实的数）",
      props: {
        hrefFor: (code) => `/types/${code}`,
        groups: [
          { key: "why", title: "为什么做", types: [
            { code: "W1", name: "研究总览", count: 140 }, { code: "W2", name: "假设模型与理论框架", count: 1326 },
            { code: "W3", name: "技术路线", count: 85 }, { code: "W5", name: "概念与机制示意", count: 802 },
          ] },
          { key: "design", title: "研究设计", types: [
            { code: "P1", name: "被试筛选流程", count: 94 }, { code: "D2", name: "试次流程", count: 692 }, { code: "D3", name: "测量时间线", count: 160 },
          ] },
          { key: "analysis", title: "分析", types: [{ code: "A1", name: "分析流程", count: 312 }, { code: "A2", name: "统计与计算模型", count: 582 }] },
          { key: "results", title: "结果", types: [{ code: "R2", name: "交互作用", count: 71 }, { code: "R9", name: "网络图", count: 39 }] },
        ],
      },
    },
  ],
});
