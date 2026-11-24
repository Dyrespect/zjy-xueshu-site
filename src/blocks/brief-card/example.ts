import { defineBlockDemo } from "@/lib/blocks";
import type { BriefView } from "@/lib/brief-types";
import { sampleBriefSettings } from "@/lib/brief-sample";

import { BriefCard } from "./BriefCard";

const { remind_after_hours: _h, minutes_step: _s, minutes_floor: _f, ...settings } = sampleBriefSettings;

const base: BriefView = {
  order_no: "00142",
  sku_name: "常规 · 1 篇",
  tier_name: "常规",
  minutes: { low: 5, high: 25, options: [5, 10, 15, 20, 25], default: 25 },
  settings,
  answers: {},
  version: 0,
  files: [],
  card: [],
  missing: [],
  state: "open",
  editable: true,
  confirmed_at: null,
  confirm_method: "",
  confirm_note: "",
  sent_back_note: "",
  stage: "claimed",
  chat_path: "/chat/x",
};

const card = [
  { key: "occasion", label: "场合", value: "组会读文献", by_default: false, missing: false },
  { key: "audience", label: "听众", value: "导师和同门（按推荐）", by_default: true, missing: false },
  { key: "minutes", label: "时长", value: "20 分钟", by_default: false, missing: false },
  { key: "language", label: "语言", value: "中文（按推荐）", by_default: true, missing: false },
  { key: "template", label: "模板", value: "没有，你们定（按推荐）", by_default: true, missing: false },
  { key: "focus", label: "重点", value: "方法讲明白、结论和证据；补充：导师上次问为什么用点探测范式", by_default: false, missing: false },
  { key: "avoid", label: "不要", value: "字太多、动画", by_default: false, missing: false },
  { key: "style", label: "风格", value: "最像「表格对照，字少留白多」", by_default: false, missing: false },
  { key: "refs", label: "参考材料", value: "2 份（上次组会.pptx、导师批注.png）", by_default: false, missing: false },
];
const answers = {
  occasion: { choice: "group" }, audience: { choice: "__default__" }, minutes: { choice: "20" }, language: { choice: "__default__" },
  template: { choice: "__default__" }, focus: { choice: ["method", "findings"], note: "导师上次问为什么用点探测范式" },
  avoid: { choice: ["wordy", "animation"] }, style: { choice: "n10" },
};
const noop = async () => undefined;
const props = { onAnswer: noop, onUpload: noop, onRemoveFile: noop, onConfirm: noop };

export default defineBlockDemo({
  block: "brief-card",
  title: "需求卡：点选、看样张、确认",
  order: 65,
  component: BriefCard,
  examples: [
    { name: "第一题：场合（上方可以全部按推荐）", props: { ...props, onAllDefault: noop, view: base, initialStep: 0 } },
    { name: "讲多久（从档位带出）", props: { ...props, view: { ...base, answers: { occasion: { choice: "group" } } }, initialStep: 2 } },
    { name: "不要什么（多选 + 一句话）", props: { ...props, view: { ...base, answers }, initialStep: 6 } },
    { name: "看样张选风格", props: { ...props, view: { ...base, answers }, initialStep: 7 } },
    { name: "传旧材料", props: { ...props, view: { ...base, answers, files: [{ id: 1, name: "上次组会.pptx", size: 2_400_000, kind: "ref" as const }] }, initialStep: 8 } },
    { name: "确认卡", props: { ...props, view: { ...base, answers, card, version: 9 } } },
    {
      name: "确认了",
      props: {
        ...props,
        onChat: () => undefined,
        view: { ...base, answers, card, state: "confirmed" as const, confirmed_at: "2026-11-19T06:12:00Z", confirm_method: "customer" as const,
          next: { text: "开工还差：主材料（论文）、哪天汇报。", where: "回到聊天发给助手", chat_path: "/chat/x" } },
      },
    },
    {
      name: "负责人改了发回",
      props: { ...props, view: { ...base, answers, card, state: "sent_back" as const, sent_back_note: "时长改成 20 分钟，按你在聊天里说的" } },
    },
  ],
});
