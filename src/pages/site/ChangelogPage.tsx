import { Container, PageHead } from "@/blocks/site-section";

import { CHANGELOG } from "./changelog";

/** 更新日志：按日期倒序，每条一个标题加几句（数据在 changelog.ts）。 */
export function ChangelogPage() {
  return (
    <>
      <PageHead eyebrow="关于" title="更新日志" lead="本站功能和规则的更新记录。用户协议、隐私政策的每次修改也会记在这里。" />
      <Container className="pb-16">
        <ol className="max-w-3xl">
          {CHANGELOG.map((e, i) => (
            <li key={i} className="grid gap-2 border-t py-8 sm:grid-cols-[8.5rem_minmax(0,1fr)] sm:gap-x-8">
              <time dateTime={e.date} className="text-sm text-muted-foreground tabular-nums">
                {e.date}
              </time>
              <div>
                <h2 className="text-lg font-semibold text-foreground">{e.title}</h2>
                <ul className="mt-2 flex flex-col gap-1.5 pl-5 [list-style:disc] marker:text-faint">
                  {e.items.map((x, j) => (
                    <li key={j} className="leading-relaxed">
                      {x}
                    </li>
                  ))}
                </ul>
              </div>
            </li>
          ))}
        </ol>
      </Container>
    </>
  );
}
