import { defineBlockDemo } from "@/lib/blocks";
import { sampleRound } from "@/lib/delivery-sample";

import { ProofViewer } from "./ProofViewer";

const noop = () => {};

export default defineBlockDemo({
  block: "proof-viewer",
  title: "交付页：逐页看水印版、标修改",
  order: 31,
  component: ProofViewer,
  examples: [
    {
      name: "标了一页要改",
      props: {
        rounds: [sampleRound(1, 2)], canMark: true, wholeMax: 3, fileMaxMb: 10, onDraftsChange: noop,
        drafts: [{ key: "a", page: 2, text: "图 3 换成原文的 Figure 2", files: [] }],
      },
    },
    { name: "两版、只看", props: { rounds: [sampleRound(1, 1), sampleRound(2, 1)], canMark: false, wholeMax: 3, fileMaxMb: 10, drafts: [], onDraftsChange: noop } },
  ],
});
