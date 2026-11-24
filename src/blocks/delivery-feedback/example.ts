import { defineBlockDemo } from "@/lib/blocks";

import { DeliveryFeedback } from "./DeliveryFeedback";

export default defineBlockDemo({
  block: "delivery-feedback",
  title: "交付页：汇报后的反馈",
  order: 35,
  component: DeliveryFeedback,
  examples: [{ name: "默认", props: { onSubmit: async () => ({ ok: true, message: "谢谢你的反馈" }) } }],
});
