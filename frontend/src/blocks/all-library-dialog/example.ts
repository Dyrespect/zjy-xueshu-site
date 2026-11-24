import { defineBlockDemo } from "@/lib/blocks";
import type { UnlockView } from "@/lib/site-types";

import { AllLibraryDialogDemo } from "./demo";

const base: UnlockView = {
  share_code: "K7M2QX",
  share_text: "心理学论文里的图，一句话就能找到，每张都带出处：https://tuku.example.org/?s=K7M2QX",
  stage: "requested",
  stage_label: "等交截图",
  verifier: "screenshot_trust",
  reason: "",
  share_visits: 0,
  need_visits: 0,
  pack_text: "",
  pack_version: "",
  follow_note: "不想转发？在公众号 PsyEngine 回复「图库」，先拿精选小包（每个图型 10 张）。",
  gzh_name: "PsyEngine",
  gzh_keyword: "图库",
};

export default defineBlockDemo({
  block: "all-library-dialog",
  title: "要全部图库",
  order: 54,
  component: AllLibraryDialogDemo,
  examples: [
    { name: "等交截图", props: { view: base } },
    {
      name: "已发链接",
      props: {
        view: {
          ...base,
          stage: "sent",
          stage_label: "已发链接",
          pack_text: "全部图库（2026.11 版，7349 张，图片和标签一起）：（网盘链接） 提取码 ab12\n图库每月更新，新版在公众号 PsyEngine 发。",
        },
      },
    },
    { name: "关注公众号", props: { view: { ...base, verifier: "follow_gzh" } } },
    { name: "还在取", props: { view: null } },
  ],
});
