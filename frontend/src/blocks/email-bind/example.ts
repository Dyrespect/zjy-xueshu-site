import { defineBlockDemo } from "@/lib/blocks";

import { EmailBind } from "./EmailBind";

const noop = () => undefined;
const start = () => Promise.resolve({ challenge: "x", masked: "la***@example.edu.cn", message: "验证码发到 la***@example.edu.cn 了，10 分钟内有效" });

export default defineBlockDemo({
  block: "email-bind",
  title: "留邮箱（可选，配了邮件服务才出现）",
  order: 66,
  component: EmailBind,
  examples: [{ name: "填邮箱", props: { open: false, onOpenChange: noop, onStart: start, onVerify: () => Promise.resolve() } }],
});
