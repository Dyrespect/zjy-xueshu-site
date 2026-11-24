import { defineBlockDemo } from "@/lib/blocks";

import { CheckoutConsent } from "./CheckoutConsent";

const none = { terms_privacy: false, ai_processing: false, custom_no_refund: false };

export default defineBlockDemo({
  block: "checkout-consent",
  title: "下单页付款前的勾选（协议、AI 处理和出境、定制不退）",
  order: 61,
  component: CheckoutConsent,
  examples: [
    { name: "还没勾", props: { checked: none, onChange: () => undefined, revisions: 1 } },
    { name: "点了付款但没勾全", props: { checked: { ...none, terms_privacy: true }, onChange: () => undefined, revisions: 1, showMissing: true } },
  ],
});
