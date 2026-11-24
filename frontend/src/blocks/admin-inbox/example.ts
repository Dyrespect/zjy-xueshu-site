import { defineBlockDemo } from "@/lib/blocks";

import { AdminInbox } from "./AdminInbox";

export default defineBlockDemo({
  block: "admin-inbox",
  title: "后台收件列表",
  order: 81,
  component: AdminInbox,
  examples: [
    {
      name: "标签反馈",
      props: {
        kind: "feedback",
        title: "标签反馈",
        filter: "all",
        onFilter: () => undefined,
        onUpdate: async (id, body) => ({ id, created_at: "2026-11-15T02:10:00Z", status: body.status ?? "done", admin_note: body.admin_note ?? "", handled_at: "2026-11-15T03:00:00Z" }),
        data: {
          kind: "feedback",
          counts: { new: 1, done: 1 },
          items: [
            {
              id: 2, created_at: "2026-11-15T02:10:00Z", status: "new", admin_note: "", handled_at: null,
              figure: { id: 16712, thumb_url: "/api/figures/16712/thumb", title: "实验1b两次注视变化的试次流程" },
              reason: "图型不对", note: "这张更像实验设计图", query: "被试内实验的试次流程",
            },
            {
              id: 1, created_at: "2026-11-14T13:40:00Z", status: "done", admin_note: "已改成 D1", handled_at: "2026-11-14T15:02:00Z",
              figure: { id: 973, thumb_url: "/api/figures/973/thumb", title: "前额近红外八乘八光源探测器与通道" },
              reason: "标签有错", note: "", query: "fNIRS 光极排布",
            },
          ],
        },
      },
    },
  ],
});
