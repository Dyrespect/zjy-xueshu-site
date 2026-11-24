import { createElement } from "react";

import { defineBlockDemo } from "@/lib/blocks";

import { AdminShell } from "./AdminShell";
import { ADMIN_NAV, withBadges } from "./nav";

export default defineBlockDemo({
  block: "admin-layout",
  title: "后台外框",
  order: 50,
  component: AdminShell,
  examples: [
    {
      name: "会话页、有 2 个客户等你批",
      props: {
        groups: withBadges(ADMIN_NAV, { "/admin/conversations": 2 }),
        activePath: "/admin/conversations/3",
        onLogout: () => undefined,
        children: createElement("div", { className: "p-8 text-sm text-muted-foreground" }, "（右边是各页的内容）"),
      },
    },
  ],
});
