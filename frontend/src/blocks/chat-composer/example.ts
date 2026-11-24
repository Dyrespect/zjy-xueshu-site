import { defineBlockDemo } from "@/lib/blocks";

import { ChatComposer } from "./ChatComposer";

export default defineBlockDemo({
  block: "chat-composer",
  title: "输入框",
  order: 11,
  component: ChatComposer,
  examples: [
    {
      name: "网页聊天（能传文件）",
      props: {
        onSendText: () => undefined,
        onSendFile: () => undefined,
        placeholder: "说说汇报：场合、几分钟、哪天",
      },
    },
    { name: "后台（你自己回）", props: { onSendText: () => undefined, placeholder: "自己回一句，直接发出去", sendLabel: "发送" } },
  ],
});
