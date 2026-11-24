import { defineBlockDemo } from "@/lib/blocks";

import { SubmitDialogDemo } from "./demo";

export default defineBlockDemo({
  block: "submit-dialog",
  title: "投图",
  order: 52,
  component: SubmitDialogDemo,
  examples: [{ name: "默认", props: {} }],
});
