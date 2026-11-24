import { defineBlockDemo } from "@/lib/blocks";
import { EMPTY_FIELDS, type InvoicePublicConfig } from "@/lib/invoice-types";

import { InvoiceOptIn } from "./InvoiceOptIn";

export const SAMPLE_CONFIG: InvoicePublicConfig = {
  enabled: true,
  kinds: [{ key: "normal", label: "电子普通发票", required: ["title", "tax_id", "email"] }],
  allow_personal: false,
  allow_remark: true,
  labels: {
    title: "抬头（单位全称）",
    tax_id: "纳税人识别号",
    email: "收发票的邮箱",
    bank_name: "开户行",
    bank_account: "银行账号",
    address: "单位地址",
    phone: "单位电话",
    remark: "发票备注",
  },
  notice: "抬头和税号开出后改不了，请对着单位财务给的信息填，提交前再核对一遍。",
  promise: "开好后发到你填的邮箱，这个页面也能下载。",
  seller_name: "杭州竹涧云科技有限公司",
  item_name: "技术服务费",
};

const noop = () => undefined;

export default defineBlockDemo({
  block: "invoice-form",
  title: "下单页：需要发票",
  order: 61,
  component: InvoiceOptIn,
  examples: [
    { name: "没勾", props: { config: SAMPLE_CONFIG, want: false, onWant: noop, value: EMPTY_FIELDS, onChange: noop } },
    {
      name: "勾了，税号位数不对",
      props: {
        config: SAMPLE_CONFIG,
        want: true,
        onWant: noop,
        value: { ...EMPTY_FIELDS, title: "清华大学", tax_id: "12100000400000624", email: "lab@example.edu.cn" },
        onChange: noop,
        errors: { tax_id: "税号是 15、18 或 20 位，现在是 17 位" },
      },
    },
  ],
});
