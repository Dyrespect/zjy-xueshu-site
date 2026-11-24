import type { BlockDemo } from "@/lib/blocks";

/**
 * /dev/blocks：开发时把所有区块用示例数据摆出来。生产构建里没有这个路由（见 App.tsx）。
 * 新区块不用改这里：在区块文件夹放 example.ts（默认导出 defineBlockDemo），自动出现。
 * 看手机宽度：用 Playwright 把视口设成 390 宽截图，或者把浏览器窗口拉窄。
 */
type DemoModule = { default: BlockDemo<object> };

const demos = Object.entries(import.meta.glob<DemoModule>("../blocks/*/example.ts", { eager: true }))
  .map(([, mod]) => mod.default)
  .sort((a, b) => (a.order ?? 100) - (b.order ?? 100) || a.block.localeCompare(b.block));

export default function DevBlocks() {
  return (
    <div className="min-h-screen bg-muted">
      <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
        <h1 className="text-2xl font-semibold">区块陈列</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          开发用：每个区块用自己的示例数据摆出来，共 {demos.length} 个。生产构建里没有这一页。
        </p>

        <div className="mt-10 flex flex-col gap-12">
          {demos.map((demo) => (
            <section key={demo.block} aria-labelledby={`block-${demo.block}`}>
              <div className="flex items-baseline gap-3">
                <h2 id={`block-${demo.block}`} className="text-lg font-semibold">
                  {demo.title}
                </h2>
                <code className="text-xs text-muted-foreground">blocks/{demo.block}</code>
              </div>
              <div className="mt-4 flex flex-col gap-6">
                {demo.examples.map((ex) => {
                  const Block = demo.component;
                  return (
                    <div key={ex.name}>
                      <div className="mb-2 text-xs text-muted-foreground">{ex.name}</div>
                      <div className="overflow-hidden rounded-lg bg-background">
                        <Block {...ex.props} />
                      </div>
                    </div>
                  );
                })}
              </div>
            </section>
          ))}
        </div>
      </div>
    </div>
  );
}
