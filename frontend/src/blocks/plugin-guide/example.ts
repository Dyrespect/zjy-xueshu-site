import { defineBlockDemo } from "@/lib/blocks";

import { PluginGuide } from "./PluginGuide";

export default defineBlockDemo({
  block: "plugin-guide",
  title: "把图库装进你的 AI",
  order: 70,
  component: PluginGuide,
  examples: [
    {
      name: "默认",
      props: {
        name: "PsyEngine 图库插件",
        mcpUrl: "https://tuku.example.org/api/gather/mcp",
        openApiUrl: "https://tuku.example.org/api/gather/open/v1/openapi.json",
        findExample: "https://tuku.example.org/api/gather/open/v1/find?q=有调节的中介模型",
      },
    },
  ],
});
