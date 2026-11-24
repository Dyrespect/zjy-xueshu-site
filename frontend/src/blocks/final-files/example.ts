import { defineBlockDemo } from "@/lib/blocks";

import { FinalFiles } from "./FinalFiles";

export default defineBlockDemo({
  block: "final-files",
  title: "交付页：最终版下载",
  order: 34,
  component: FinalFiles,
  examples: [
    {
      name: "放出了",
      props: {
        final: {
          released: true, waiting: false,
          files: [
            { id: 1, name: "卡尼曼与网络成瘾_组会.pptx", kind: "PPT", size: 18_400_000, url: "#" },
            { id: 2, name: "讲稿.docx", kind: "讲稿", size: 41_000, url: "#" },
          ],
        },
      },
    },
    { name: "已完成、还在传", props: { final: { released: false, waiting: true, files: [] } } },
  ],
});
