import { defineBlockDemo } from "@/lib/blocks";

import { RequestDialogDemo } from "./demo";

export default defineBlockDemo({
  block: "request-dialog",
  title: "提需求",
  order: 51,
  component: RequestDialogDemo,
  examples: [{ name: "从结果页底部点开（带上搜的话）", props: { query: "催眠诱导的流程" } }],
});
