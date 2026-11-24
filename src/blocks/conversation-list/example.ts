import { defineBlockDemo } from "@/lib/blocks";

import { ConversationList } from "./ConversationList";

const now = new Date().toISOString();

export default defineBlockDemo({
  block: "conversation-list",
  title: "会话列表",
  order: 51,
  component: ConversationList,
  examples: [
    {
      name: "有待批的排前面",
      props: {
        activeId: 2,
        hrefFor: (id: number) => `/admin/conversations/${id}`,
        rows: [
          { id: 2, name: "海的湛蓝", channel: "wecom", source: "小红书", status: "collecting", status_label: "收集中", last_text: "有偿可以排上做吗，钱不是问题", last_from: "customer", last_at: now, pending: 1, failed: 0, needs: 2, takeover: false },
          { id: 5, name: "青柚", channel: "web", source: "", status: "confirming", status_label: "待确认", last_text: "下下周三汇报，讲20分钟吧。俺是浙江师大的", last_from: "customer", last_at: now, pending: 1, failed: 0, needs: 0, takeover: false },
          { id: 3, name: "柳沐", channel: "wecom", source: "公众号文章", status: "in_production", status_label: "制作中", last_text: "排上啦，预计 11月20日（周五）前发你第一版。", last_from: "system", last_at: now, pending: 0, failed: 0, needs: 0, takeover: false },
          { id: 7, name: "杭杭吖", channel: "wecom", source: "", status: "confirming", status_label: "待确认", last_text: "这个我这边处理不了，可以加负责人的微信", last_from: "bot", last_at: now, pending: 0, failed: 1, needs: 1, takeover: true },
        ],
      },
    },
    { name: "空", props: { rows: [], hrefFor: (id: number) => `/admin/conversations/${id}` } },
  ],
});
