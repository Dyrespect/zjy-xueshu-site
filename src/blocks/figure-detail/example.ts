import { defineBlockDemo } from "@/lib/blocks";

import { EXAMPLE_CARDS, EXAMPLE_DETAIL } from "../figure-card/example-data";
import { FigureDetailView, type FigureDetailViewProps } from "./FigureDetailView";

const base: FigureDetailViewProps = {
  detail: EXAMPLE_DETAIL,
  similar: EXAMPLE_CARDS.slice(1),
  searchHref: (w) => `/search?q=${encodeURIComponent(w)}`,
  typeHref: (c) => `/types/${c}`,
  cardHref: (c) => `/figure/${c.id}`,
  onFeedback: () => undefined,
  onSubmitFigure: () => undefined,
  onAllLibrary: () => undefined,
};

export default defineBlockDemo({
  block: "figure-detail",
  title: "图详情",
  order: 40,
  component: FigureDetailView,
  examples: [
    { name: "默认", props: base },
    { name: "加载中", props: { ...base, detail: null, similar: null, loading: true } },
  ],
});
