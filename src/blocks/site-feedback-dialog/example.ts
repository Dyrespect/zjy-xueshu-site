import { defineBlockDemo } from "@/lib/blocks";

import { SiteFeedbackDialogDemo } from "./demo";

export default defineBlockDemo({
  block: "site-feedback-dialog",
  title: "意见反馈",
  order: 53,
  component: SiteFeedbackDialogDemo,
  examples: [{ name: "默认", props: {} }],
});
