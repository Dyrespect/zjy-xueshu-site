import { defineBlockDemo } from "@/lib/blocks";

import { LegalDoc, type LegalDocData } from "./LegalDoc";

const doc: LegalDocData = {
  title: "免责声明",
  version: "2026-11-18",
  lead: "我们怎么做、你要自己把关的地方。",
  open: ["要不要写一个赔偿上限"],
  basis: "底稿：示例。",
  markdown: [
    "## AI 辅助制作 {#ai}",
    "PPT 由人和 AI 一起做，详见[隐私政策](/privacy#ai)。",
    "- **内容**以你的材料为准",
    "- 上台前请自己过一遍",
    "## 联系我们 {#contact}",
    "电话 {phone}（{phone_note}）。",
  ].join("\n\n"),
};

export default defineBlockDemo({
  block: "legal-doc",
  title: "协议类长文（草稿提示、目录、Markdown 正文）",
  order: 9,
  component: LegalDoc,
  examples: [{ name: "示例", props: { doc, vars: { phone: "15068998671", phone_note: "微信同号" } } }],
});
