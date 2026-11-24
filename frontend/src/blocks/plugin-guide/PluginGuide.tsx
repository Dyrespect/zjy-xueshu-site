import { toast } from "sonner";

import { Button } from "@/components/ui/button";

export interface PluginGuideProps {
  /** 插件对外的名字（后台聚人设置里改；Edison 还没定，默认「PsyEngine 图库插件」） */
  name: string;
  /** 远程 MCP 地址（Claude、Cherry Studio、Cursor、Trae、Claude Code 填这一个网址） */
  mcpUrl: string;
  /** 开放接口文档（OpenAPI） */
  openApiUrl: string;
  /** 开放接口找图的例子 */
  findExample: string;
}

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast.success("复制好了");
  } catch {
    toast.error("没复制成功，手动选中复制");
  }
}

function CopyLine({ value, label }: { value: string; label?: string }) {
  return (
    <div className="flex min-w-0 items-center gap-2 rounded-md border bg-card px-3 py-2">
      {label ? <span className="shrink-0 text-xs text-muted-foreground">{label}</span> : null}
      <code className="min-w-0 flex-1 truncate text-sm text-foreground">{value}</code>
      <Button variant="outline" size="sm" onClick={() => copy(value)}>
        复制
      </Button>
    </div>
  );
}

const CLIENTS: { name: string; steps: string }[] = [
  { name: "Claude（网页、桌面、手机）", steps: "设置 → 连接器 → 添加自定义连接器，名字随便写，网址填上面这个。免费版能加 1 个。" },
  { name: "Cherry Studio", steps: "设置 → MCP 服务器 → 添加，类型选「可流式 HTTP」，网址填上面这个。" },
  { name: "Cursor、Trae", steps: "设置 → MCP → 添加，类型选 HTTP（streamable），网址填上面这个。" },
];

/** 「把图库装进你的 AI」：一个地址三个外壳（远程 MCP、开放接口、skill 在线模式），底下都是网站搜索框那一个检索。 */
export function PluginGuide({ name, mcpUrl, openApiUrl, findExample }: PluginGuideProps) {
  const cmd = `claude mcp add --transport http psyengine-figures ${mcpUrl}`;
  return (
    <div className="flex flex-col gap-10">
      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">能填网址的 AI：填这一个地址</h2>
        <CopyLine value={mcpUrl} />
        <ul className="flex flex-col gap-3">
          {CLIENTS.map((c) => (
            <li key={c.name} className="text-[15px] leading-relaxed text-body">
              <span className="font-medium text-foreground">{c.name}</span>：{c.steps}
            </li>
          ))}
          <li className="flex flex-col gap-2 text-[15px] leading-relaxed text-body">
            <span>
              <span className="font-medium text-foreground">Claude Code</span>：在终端跑这一行。
            </span>
            <CopyLine value={cmd} />
          </li>
        </ul>
        <p className="text-[15px] text-body">装好以后跟 AI 说一句「用 {name} 找有调节的中介模型怎么画」，它会拿回十几张带出处、带网站链接的图。</p>
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">写脚本、智能体平台：开放接口</h2>
        <p className="text-[15px] text-body">不用登录、不收费，每个 IP 每小时有次数上限。接口文档是标准的 OpenAPI，扣子、GPTs 这类平台能直接导入。</p>
        <CopyLine label="接口文档" value={openApiUrl} />
        <CopyLine label="找图例子" value={findExample} />
      </section>

      <section className="flex flex-col gap-3">
        <h2 className="text-lg font-semibold">DeepSeek、豆包、元宝的网页版</h2>
        <p className="text-[15px] text-body">这几家现在不能自己加插件，直接用网站上的搜索框，结果一样。</p>
      </section>
    </div>
  );
}
