import { defineBlockDemo } from "@/lib/blocks";

import { FigureGridDemo, type FigureGridDemoProps } from "./demo";
import { EXAMPLE_CARDS } from "./example-data";

export default defineBlockDemo<FigureGridDemoProps>({
  block: "figure-card",
  title: "图卡片",
  order: 20,
  component: FigureGridDemo,
  examples: [
    { name: "一组结果", props: { cards: EXAMPLE_CARDS, hrefFor: (c) => `/figure/${c.id}` } },
    { name: "加载中", props: { cards: [], hrefFor: () => "#", loading: true } },
  ],
});
