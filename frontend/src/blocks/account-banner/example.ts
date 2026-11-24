import { defineBlockDemo } from "@/lib/blocks";

import { AccountBanner } from "./AccountBanner";

export default defineBlockDemo({
  block: "account-banner",
  title: "交付页、需求卡、聊天页顶上：登录后记到你的账号",
  order: 69,
  component: AccountBanner,
  examples: [
    { name: "没登录", props: { state: "login", loginHref: "/login?next=/d/x" } },
    { name: "登录了、这单还是匿名的", props: { state: "bind", loginHref: "/login", onBind: () => undefined } },
    { name: "记过来了", props: { state: "bind", loginHref: "/login", done: "记到你的账号下了，以后在「我的订单」里就能看到" } },
  ],
});
