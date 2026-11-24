import { defineBlockDemo } from "@/lib/blocks";

import { PhoneBind } from "./PhoneForm";

const start = () => Promise.resolve({ masked: "138****5678", message: "验证码发到 138****5678 了，5 分钟内有效", ttl_min: 5 });

export default defineBlockDemo({
  block: "phone-bind",
  title: "绑定手机号（短信开着才出现）",
  order: 68,
  component: PhoneBind,
  examples: [
    { name: "需求卡顶上", props: { onStart: start, onVerify: () => Promise.resolve(), onSkip: () => undefined } },
    { name: "我的订单里（小一号、不给跳过）", props: { onStart: start, onVerify: () => Promise.resolve(), compact: true } },
  ],
});
