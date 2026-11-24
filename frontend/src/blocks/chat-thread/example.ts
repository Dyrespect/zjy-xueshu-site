import { defineBlockDemo } from "@/lib/blocks";

import { ChatThread } from "./ChatThread";

// 陈列页用的「二维码」示意图（真图在服务器上，OWNER_WECHAT_QR）
const QR_DEMO =
  "data:image/svg+xml;utf8," +
  encodeURIComponent(
    "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 21 21' shape-rendering='crispEdges'>" +
      "<path d='M0 0h7v7H0zM2 2v3h3V2zM14 0h7v7h-7zM16 2v3h3V2zM0 14h7v7H0zM2 16v3h3v-3z' fill-rule='evenodd'/>" +
      "<path d='M9 1h2v2H9zM9 5h3v2H9zM8 9h4v2H8zM13 9h2v3h-2zM16 10h3v2h-3zM9 13h2v4H9zM12 14h3v2h-3zM16 14h2v5h-2zM12 18h3v2h-3zM19 17h2v2h-2z'/>" +
      "</svg>",
  );

export default defineBlockDemo({
  block: "chat-thread",
  title: "对话气泡",
  order: 10,
  component: ChatThread,
  examples: [
    {
      name: "网页聊天（客户看到的）",
      props: {
        messages: [
          { id: 1, side: "left", kind: "text", text: "同学你好哦，我是 PsyEngine 的接单助手（AI）。把要汇报的材料发我（论文 PDF、开题报告这些），再说下讲几分钟、哪天汇报，我帮你看能不能排上、多少钱。", time: "14:02" },
          { id: 2, side: "right", kind: "text", text: "我想做组会汇报的PPT，下下周三汇报，讲20分钟", time: "14:05" },
          { id: 3, side: "right", kind: "file", text: "", file: { name: "Affiliation in human-AI interactions is based on shared psychological traits.pdf", size: 1357348, url: "#" }, time: "14:05" },
          { id: 4, side: "left", kind: "text", text: "收到啦，论文看到了。文献·标准 19.9 元，最早 11月16日（周一）前就能交，要做吗", time: "14:06" },
        ],
      },
    },
    {
      name: "交付什么 + 注意事项、负责人微信",
      props: {
        messages: [
          { id: 1, side: "right", kind: "text", text: "可以，就标准的吧", time: "14:08" },
          {
            id: 2, side: "left", kind: "text", card: "terms", time: "14:08",
            text: "文献·标准：19.9 元，标准用时（组会文献 1 天），按排队\n\n你会拿到：① 可编辑的 PPT，按你说的时长做；② 每页的讲稿（Word），照着能讲；③ 学校校徽和配色，或者套你发来的模板；④ 原文的图照用，原文没有、讲不清的我们按心理学好刊的画法画出来；⑤ 内容标出处，APA 格式；⑥ 含一次免费修改。\n\n注意事项：\n1. 内容以开工时你发来的材料为准，开工后再加新的内容算新的一单；\n2. 交付时间按排队，开工时告诉你；\n3. 你的开题报告、数据和草稿不公开，也不会拿去当示例；\n4. 我们不代写论文、不编数据；\n5. 激活码核销后开工；开工前想撤单，码退回给你还能用；开工后不退；\n6. 上台前请自己过一遍，按老师的要求微调。",
          },
          { id: 3, side: "left", kind: "text", text: "上面是我们会交付的和注意事项，你看下没问题的话，有激活码直接发我，没有的话我把付款方式发你", time: "14:08" },
          { id: 4, side: "right", kind: "text", text: "能便宜点吗，学生党", time: "14:10" },
          { id: 5, side: "left", kind: "text", text: "价格是按档位定的哈，想谈的话可以加负责人的微信", time: "14:10" },
          { id: 6, side: "left", kind: "image", card: "owner_qr", text: "负责人微信二维码", imageUrl: QR_DEMO, time: "14:10" },
        ],
      },
    },
    {
      name: "要发的资料（场合定了系统发一遍）",
      props: {
        messages: [
          { id: 1, side: "right", kind: "text", text: "中期用的，这是开题报告", time: "15:02" },
          { id: 2, side: "left", kind: "text", text: "收到啦，要发的我列在下面了", time: "15:02" },
          { id: 3, side: "left", kind: "text", card: "materials", time: "15:02", text: "中期要发这几样，直接发在这里，一次发齐最快：\n\n必须发的：\n· 开题报告（或开题 PPT）：交代研究问题和当初的计划（收到了）\n· 现在的进展（文稿、PPT、跑出来的结果图都行）：讲做了什么、结果怎样、接下来做什么\n· 哪天汇报：排期，看赶不赶得上\n\n有的话更好：\n· 学校模板：有就照它做，没有就用学校配色\n· 实验材料：照着画实验流程\n· 分析好的结果图：结果页直接照它讲\n· 学校名：放校徽和配色\n\n资料齐了才开工，时限从开工那会儿算，不是从付款算。" },
        ],
      },
    },
    {
      name: "后台（带发言人）",
      props: {
        messages: [
          { id: 1, side: "left", who: "海的湛蓝", kind: "text", text: "汇报时长：15min，下周三下午四五点汇报", time: "11月8日 06:00" },
          { id: 2, side: "right", who: "助手", kind: "text", text: "收到，15 分钟、周三下午汇报记下了。论文发我就行", time: "11月8日 06:02" },
          { id: 3, side: "right", who: "你", kind: "text", text: "可以的，明天晚上发你第一版", time: "11月8日 07:01" },
        ],
      },
    },
    { name: "还没有消息", props: { messages: [], emptyText: "还没有消息" } },
  ],
});
