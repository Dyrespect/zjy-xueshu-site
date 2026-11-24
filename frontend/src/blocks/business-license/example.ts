import { defineBlockDemo } from "@/lib/blocks";

import { LicenseView } from "./LicenseView";

export default defineBlockDemo({
  block: "business-license",
  title: "营业执照公示（电子商务法第十五条）",
  order: 90,
  component: LicenseView,
  examples: [
    {
      name: "执照信息",
      props: {
        info: { company_name: "示例科技有限公司", credit_code: "91330110XXXXXXXXXX", license_type: "有限责任公司（自然人独资）",
          legal_rep: "张三", reg_address: "浙江省杭州市某区某路 1 号", established: "2026-01-01", registry_authority: "某区市场监督管理局" },
        imageMissing: true,
      },
    },
  ],
});
