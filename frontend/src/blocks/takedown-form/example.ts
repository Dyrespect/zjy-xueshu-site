import { defineBlockDemo } from "@/lib/blocks";

import { TakedownForm } from "./TakedownForm";

export default defineBlockDemo({
  block: "takedown-form",
  title: "版权问题",
  order: 71,
  component: TakedownForm,
  examples: [
    {
      name: "默认",
      props: { hours: 48, onSubmit: async () => ({ message: "收到了。" }), onDone: () => undefined },
    },
  ],
});
