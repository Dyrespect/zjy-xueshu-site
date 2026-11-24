import { defineBlockDemo } from "@/lib/blocks";
import { sampleBriefSettings } from "@/lib/brief-sample";

import { BriefSettingsForm } from "./BriefSettingsForm";

export default defineBlockDemo({
  block: "brief-settings",
  title: "后台设置：需求卡",
  order: 66,
  component: BriefSettingsForm,
  examples: [{ name: "默认设置", props: { settings: sampleBriefSettings, onSave: async () => undefined } }],
});
