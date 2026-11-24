import { PluginGuide } from "@/blocks/plugin-guide";

import { useGallery, useTitle } from "./gallery-context";

/** /plugin 把图库装进你的 AI（插件名字在后台聚人设置里，默认「PsyEngine 图库插件」）。 */
export default function PluginPage() {
  const { map } = useGallery();
  const name = map?.plugin_name ?? "PsyEngine 图库插件";
  useTitle(name);
  const base = (map?.bases.figures || window.location.origin).replace(/\/$/, "");
  return (
    <main className="mx-auto max-w-3xl px-4 pt-8 pb-16 sm:px-6 sm:pt-12">
      <h1 className="text-2xl font-semibold">把图库装进你的 AI：{name}</h1>
      <p className="mt-2 text-[15px] text-body">
        在你自己的 AI 里直接问「这种图怎么画」，拿回带出处的论文图和网站链接。和网站搜索框是同一个检索，不收费。
      </p>
      <div className="mt-10">
        <PluginGuide
          name={name}
          mcpUrl={`${base}/api/gather/mcp`}
          openApiUrl={`${base}/api/gather/open/v1/openapi.json`}
          findExample={`${base}/api/gather/open/v1/find?q=${encodeURIComponent("有调节的中介模型")}`}
        />
      </div>
    </main>
  );
}
