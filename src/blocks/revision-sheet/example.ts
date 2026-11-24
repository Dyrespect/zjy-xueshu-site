import { defineBlockDemo } from "@/lib/blocks";

import { RevisionSheet } from "./RevisionSheet";

const noop = () => {};

export default defineBlockDemo({
  block: "revision-sheet",
  title: "交付页：提交前核对修改意见（弹层）",
  order: 32,
  component: RevisionSheet,
  examples: [
    {
      name: "打开（真页面里是弹层，陈列页默认关着）",
      props: {
        open: false, revisionsLeft: 1, afterDelivery: false, busy: false, onOpenChange: noop, onSubmit: noop,
        drafts: [
          { key: "a", page: 5, text: "时间轴太挤，1971—1972 那个点挪到下面一行", files: [] },
          { key: "b", page: null, text: "标题字再大一号", files: [] },
        ],
      },
    },
  ],
});
