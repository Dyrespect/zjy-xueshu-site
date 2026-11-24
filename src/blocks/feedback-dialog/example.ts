import { defineBlockDemo } from "@/lib/blocks";

import { FeedbackDialogDemo } from "./demo";

export default defineBlockDemo({
  block: "feedback-dialog",
  title: "标签不对 / 不相关",
  order: 50,
  component: FeedbackDialogDemo,
  examples: [{ name: "从搜索结果点进来", props: { query: "被试内实验的试次流程" } }],
});
