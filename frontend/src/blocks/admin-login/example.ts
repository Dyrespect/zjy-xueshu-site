import { defineBlockDemo } from "@/lib/blocks";

import { LoginForm } from "./LoginForm";

export default defineBlockDemo({
  block: "admin-login",
  title: "后台登录",
  order: 49,
  component: LoginForm,
  examples: [{ name: "默认", props: { onSubmit: async () => undefined } }],
});
