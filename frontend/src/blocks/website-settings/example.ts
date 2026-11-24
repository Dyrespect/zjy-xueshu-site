import { defineBlockDemo } from "@/lib/blocks";

import { WebsiteSettingsForm } from "./WebsiteSettingsForm";

export default defineBlockDemo({
  block: "website-settings",
  title: "后台：官网设置（页脚主体信息、公安备案号、公开开关、维护中）",
  order: 120,
  component: WebsiteSettingsForm,
  examples: [
    {
      name: "默认（公安备案号、邮箱、客服时间待填）",
      props: {
        data: {
          config: {
            company_name: "杭州竹涧云科技有限公司",
            credit_code: "91330110MAKFUNHCXY",
            icp: "浙ICP备2026046510号-1",
            police_beian: "",
            phone: "15068998671",
            phone_note: "微信同号",
            email: "",
            address: "",
            service_hours: "",
            reply_promise: "一般 1 个工作日内答复",
            indexable: false,
            maintenance: false,
            maintenance_text: "网站正在维护，预计很快恢复。如有急事，请拨打客服电话。",
          },
          launch_fields: {
            police_beian: "公安联网备案号（网站开通后到全国互联网安全管理服务平台备案，拿到号填这里）",
            email: "对外邮箱（隐私和投诉的书面渠道；没有就只留电话）",
            service_hours: "客服时间（写了客人知道什么时候有人回）",
          },
          pending_launch: ["police_beian", "email", "service_hours"],
        },
        onSave: async () => undefined,
      },
    },
  ],
});
