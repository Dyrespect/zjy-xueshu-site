import { defineBlockDemo } from "@/lib/blocks";

import { GatherNumbers } from "./AdminGather";

export default defineBlockDemo({
  block: "admin-gather",
  title: "后台：聚人数",
  order: 90,
  component: GatherNumbers,
  examples: [
    {
      name: "一周",
      props: {
        data: {
          days: 7,
          visits: 128,
          visits_by_src: [
            { src: "gzh", n: 60 },
            { src: "share", n: 40 },
            { src: "xhs", n: 28 },
          ],
          share_new_visitors: 40,
          unlock_requested: 30,
          unlock_evidence: 22,
          unlock_sent: 21,
          top_sharers: [{ share_code: "K7M2QX", visits: 9, stage: "sent" }],
          cta_clicks: [{ what: "unlock_done→order", n: 5 }],
          search_by_caller: { web: 300, ai: 12 },
          orders_from_tuku: 2,
          grants: 21,
        },
      },
    },
  ],
});
