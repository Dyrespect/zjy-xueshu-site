import { defineBlockDemo } from "@/lib/blocks";
import type { ReceptionKB } from "@/lib/reception-types";

import { ReceptionSettingsForm } from "./ReceptionSettingsForm";

const kb: ReceptionKB = {
  version: 1,
  disclosure: {
    text: "同学你好呀，这里是 PsyEngine，我是 AI 助手小鱼，下面的回复由 AI 生成，负责人随时看记录与接手",
    window_days: 7,
    web_footer: "小鱼是 AI 助手，回复由 AI 生成 · 负责人随时看记录与接手",
  },
  persona: { name: "小鱼", who: "PsyEngine 的 AI 接单助手，学姐气质", never: "不编自己读研的经历" },
  owner: { wechat: "15000000000", line: "负责人微信 15000000000（同号），加的时候备注 PsyEngine", mute_after_handoff: true },
  style: {
    max_chars_per_msg: 45,
    max_chars_per_turn: 110,
    max_segments: { web: 3, wecom: 2 },
    banned: [
      { text: "您", why: "跟同学说「你」" },
      { text: "希望对你有帮助", why: "AI 结尾句" },
    ],
    banned_patterns: [],
    fillers: ["我看下哈", "稍等哈，我查一下"],
  },
  rhythm: { first_min_s: 4, first_max_s: 40, typing_chars_per_s: 2.5, read_per_char_s: 0.08, night_factor: 1.5, night_max_s: 75,
    filler_every_hours: 2, night_from: "00:30", night_to: "07:30" },
  asks: [],
  samples: [
    { title: "从常规化验中识别抑郁线索", about: "组会文献汇报，16 页", filename: "样张1.pdf", size: 3600000, ready: true },
    { title: "大语言模型识别自杀意念", about: "组会文献汇报，22 页", filename: "", size: 0 },
  ],
  gzh_line: "公众号 PsyEngine 每天发一篇免费的文献汇报 PPT",
  intents: [
    { id: "ask_price", name: "问价", stage: "售前", desc: "问多少钱", examples: ["多少钱", "怎么收费"], keywords: ["多少钱"], decisive: false,
      reply: "知道时长就用 quote_price 算好再说", next: "问哪天汇报", handoff: "要打折、坚持谈价", samples: ["客人：多少钱\n我：大概讲多久、几篇呀"] },
    { id: "ask_bot", name: "问是不是机器人", stage: "任何时候", desc: "问你是真人吗", examples: ["你是真人吗"], keywords: ["真人"], decisive: true,
      reply: "照实说是 AI 助手", next: "接回他刚才在问的事", handoff: "", samples: [] },
  ],
};

export default defineBlockDemo({
  block: "reception-settings",
  title: "后台设置：接待机器人",
  order: 67,
  component: ReceptionSettingsForm,
  examples: [
    {
      name: "默认设置",
      props: {
        kb,
        onSave: async () => undefined,
        onTry: async () => ({ intents: [{ id: "ask_price", name: "问价" }], how: "rules", answering: false, scores: [], reply: [{ text: "大概讲多久呀", after_s: 8.2 }] }),
      },
    },
  ],
});
