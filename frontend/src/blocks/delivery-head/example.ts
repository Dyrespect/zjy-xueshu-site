import { defineBlockDemo } from "@/lib/blocks";
import { sampleDelivery } from "@/lib/delivery-sample";

import { DeliveryHead } from "./DeliveryHead";

export default defineBlockDemo({
  block: "delivery-head",
  title: "交付页：标题和进度",
  order: 30,
  component: DeliveryHead,
  examples: [
    {
      name: "制作中",
      props: { data: { ...sampleDelivery, stage: "making", status: "制作中", step: 1, delivered: false, rounds: [], due_text: "开工了，预计 11月18日（周三）21:30前交第一版水印版。" } },
    },
    { name: "已交水印版", props: { data: sampleDelivery } },
  ],
});
