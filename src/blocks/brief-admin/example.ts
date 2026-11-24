import { defineBlockDemo } from "@/lib/blocks";
import type { BriefAdminView } from "@/lib/brief-types";
import { sampleBriefSettings } from "@/lib/brief-sample";

import { BriefAdmin } from "./BriefAdmin";

const { remind_after_hours: _h, minutes_step: _s, minutes_floor: _f, ...settings } = sampleBriefSettings;
const card = [
  { key: "occasion", label: "场合", value: "组会读文献", by_default: false, missing: false },
  { key: "audience", label: "听众", value: "导师和同门（按推荐）", by_default: true, missing: false },
  { key: "minutes", label: "时长", value: "20 分钟", by_default: false, missing: false },
  { key: "language", label: "语言", value: "中文（按推荐）", by_default: true, missing: false },
  { key: "template", label: "模板", value: "没有，你们定（按推荐）", by_default: true, missing: false },
  { key: "avoid", label: "不要", value: "字太多、动画", by_default: false, missing: false },
  { key: "style", label: "风格", value: "最像「表格对照，字少留白多」", by_default: false, missing: false },
  { key: "refs", label: "参考材料", value: "1 份（导师批注.png）", by_default: false, missing: false },
];
const base: BriefAdminView = {
  order_no: "00142", sku_name: "常规 · 1 篇", tier_name: "常规", minutes: { low: 5, high: 25, options: [5, 10, 15, 20, 25], default: 25 },
  settings, answers: { occasion: { choice: "group" }, minutes: { choice: "20" } }, version: 3, files: [], card, missing: [],
  state: "open", editable: true, confirmed_at: null, confirm_method: "", confirm_note: "", sent_back_note: "", stage: "collecting",
  order_id: 142, url: "https://psyppt.pilipala.zj.cn/b/Fq2kZ8", condition: { ok: false, detail: "客人选了一部分，还没点「对，开工」" },
  card_text: "", confirmed_by: "", history: [{ at: "2026-11-19T05:40:00Z", what: "改了需求卡", who: "客人", note: "" }],
};
const noop = async () => undefined;

export default defineBlockDemo({
  block: "brief-admin",
  title: "后台订单卡：需求卡",
  order: 67,
  component: BriefAdmin,
  examples: [
    { name: "等客人确认", props: { view: base, onSendBack: noop, onProxy: noop } },
    { name: "代确认了", props: { view: { ...base, state: "confirmed" as const, confirm_method: "proxy" as const, confirm_note: "客人在聊天里说「可以，就这样」",
      confirmed_at: "2026-11-19T06:02:00Z", condition: { ok: true, detail: "负责人代确认" } }, onSendBack: noop, onProxy: noop } },
  ],
});
