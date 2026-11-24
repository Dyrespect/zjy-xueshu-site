import { defineBlockDemo } from "@/lib/blocks";

import { AdminSearchStats } from "./AdminSearchStats";

export default defineBlockDemo({
  block: "admin-search-stats",
  title: "后台搜索统计",
  order: 82,
  component: AdminSearchStats,
  examples: [
    {
      name: "默认",
      props: {
        searchHref: (q) => `/search?q=${encodeURIComponent(q)}`,
        stats: {
          today: 12,
          week: 86,
          zero_words: [
            { word: "催眠诱导", n: 3 },
            { word: "房树人", n: 2 },
          ],
          top_clicked: [
            { id: 16712, thumb_url: "/api/figures/16712/thumb", title: "实验1b两次注视变化的试次流程", n: 5 },
            { id: 973, thumb_url: "/api/figures/973/thumb", title: "前额近红外八乘八光源探测器与通道", n: 3 },
          ],
          recent: [
            { id: 86, created_at: "2026-11-15T02:12:00Z", query: "被试内实验的试次流程", code_name: "试次流程", total: 16, zero_words: [] },
            { id: 85, created_at: "2026-11-15T02:05:00Z", query: "催眠诱导的流程", code_name: "试次流程", total: 40, zero_words: ["催眠诱导"] },
          ],
        },
      },
    },
  ],
});
