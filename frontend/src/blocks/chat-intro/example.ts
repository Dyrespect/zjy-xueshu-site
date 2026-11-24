import { defineBlockDemo } from "@/lib/blocks";

import { ChatIntro } from "./ChatIntro";

export default defineBlockDemo({
  block: "chat-intro",
  title: "网页聊天顶部",
  order: 12,
  component: ChatIntro,
  examples: [
    { name: "聊着", props: { returnUrl: "http://127.0.0.1:5175/chat/Kq3xV9mTt2bLw8RzYp0aHf1cNe5uDj7s" } },
    { name: "认领了（可留邮箱）", props: { returnUrl: "http://127.0.0.1:5175/chat/Kq3xV9mTt2bLw8RzYp0aHf1cNe5uDj7s",
      order: { order_no: "00012", sku_name: "常规 · 1 篇", stage_label: "收资料" }, account: "bind" as const } },
    { name: "做好了", props: { returnUrl: "http://127.0.0.1:5175/chat/Kq3xV9mTt2bLw8RzYp0aHf1cNe5uDj7s", deliveryPath: "/d/q8Hc2vYtW1nM0aXbLr4sK7pE9dJf" } },
  ],
});
