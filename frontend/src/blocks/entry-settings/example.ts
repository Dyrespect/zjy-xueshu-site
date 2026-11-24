import { defineBlockDemo } from "@/lib/blocks";

import { EntrySettings } from "./EntrySettings";

const ok = () => Promise.resolve();

export default defineBlockDemo({
  block: "entry-settings",
  title: "后台：入口（微信客服、限额、资料清单）",
  order: 210,
  component: EntrySettings,
  examples: [{
    name: "微信客服还没开",
    props: {
      data: {
        config: { wecom_enabled: false, wecom_links: {}, wecom_reserve_for_delivery: 2, wecom_welcome_max_age_s: 15,
          redeem_entries: ["entry.webchat", "entry.wecom"], redeem_ip_hourly: 60, web_visitor_ip_daily: 60, buy_places: [],
          code_hint: "", site_url: "https://psyppt.pilipala.zj.cn", confirm_phrases: ["确认收货", "确认"] },
        wecom: { configured: { corpid: false, secret: false, token: false, aes_key: false, open_kfid: false }, client_ready: false,
          available: false, reason: "微信客服还没开（后台「入口」页的开关）", callback_path: "/api/channels/wecom/callback" },
        email: { enabled: false, via: "" },
        checklists: { default: { items: [{ key: "occasion", label: "什么场合", kind: "fact", required: true }] } },
        visitor: { daily: 20, global_daily: 500 },
        entries: [],
      },
      onSave: ok,
      onMakeLink: ok,
    },
  }],
});
