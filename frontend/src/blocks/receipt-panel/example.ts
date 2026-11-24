import { defineBlockDemo } from "@/lib/blocks";
import { sampleDelivery } from "@/lib/delivery-sample";

import { ReceiptPanel } from "./ReceiptPanel";

const noop = () => {};
const base = { revision: sampleDelivery.revision, busy: null, onReview: noop, onConfirm: noop, onPlatformClaim: noop, inline: true };

export default defineBlockDemo({
  block: "receipt-panel",
  title: "交付页：底部确认收货条（真页面里贴在底部）",
  order: 33,
  component: ReceiptPanel,
  examples: [
    { name: "自有渠道、标了 2 处", props: { ...base, receipt: sampleDelivery.receipt, marked: 2 } },
    {
      name: "平台单",
      props: {
        ...base, marked: 0,
        receipt: { ...sampleDelivery.receipt, mode: "platform" as const, platform_name: "闲鱼", auto_confirm_text: "",
                   hint: "满意的话到闲鱼订单里点「确认收货」，平台确认后这个页面会放出可编辑的 PPT 和讲稿。" },
      },
    },
  ],
});
