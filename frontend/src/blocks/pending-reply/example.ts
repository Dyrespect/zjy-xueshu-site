import { defineBlockDemo } from "@/lib/blocks";

import { PendingReply } from "./PendingReply";

const now = new Date().toISOString();
const noop = async () => undefined;

export default defineBlockDemo({
  block: "pending-reply",
  title: "待批的回复",
  order: 52,
  component: PendingReply,
  examples: [
    {
      name: "机器人收到文件后想发",
      props: {
        onSend: noop,
        onReject: noop,
        item: {
          id: 12, status: "pending", status_label: "待批", kind: "text", asset: "", author: "bot", auto: false, error: "", original_text: "", created_at: now,
          text: "收到啦，论文和补充材料都看到了。大概讲几分钟、哪天汇报呀？",
          category: "收到文件",
          reasons: ["登记附件：Affiliation in human-AI interactions is based on shared psychological traits.pdf → 论文", "登记附件：[Supplementary Information].pdf → 材料"],
          run: { id: 3, model: "deepseek-v4.1-flash", tools: [], error: "", requests: 2, input_tokens: 4180, output_tokens: 96, started_at: now },
        },
      },
    },
    {
      name: "微信客服发满 5 条",
      props: {
        onSend: noop,
        onReject: noop,
        blockedReason: "48 小时内已经发满 5 条，等客户再说一句",
        item: {
          id: 13, status: "failed", status_label: "发送失败", kind: "text", asset: "", author: "system", auto: false, original_text: "", created_at: now,
          text: "排上啦，预计 11月18日（周三）前发你第一版。", category: "排期通知", reasons: ["五个开工条件都满足了，代码自动排进队"],
          error: "48 小时内已经发满 5 条，等客户再说一句才能发", run: null,
        },
      },
    },
  ],
});
