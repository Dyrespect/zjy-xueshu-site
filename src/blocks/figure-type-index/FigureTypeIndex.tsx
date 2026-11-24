import { Link } from "react-router";

import type { TypeGroup } from "@/lib/figures-types";

export interface FigureTypeIndexProps {
  title?: string;
  groups: TypeGroup[];
  hrefFor: (code: string) => string;
}

/** 首页下半：按「这张图在汇报里干什么用」分四组，列出全部图型和库里有几张 */
export function FigureTypeIndex({ title = "按图在汇报里的用途找", groups, hrefFor }: FigureTypeIndexProps) {
  return (
    <section aria-labelledby="type-index-title">
      <h2 id="type-index-title" className="text-xl font-semibold">
        {title}
      </h2>
      <div className="mt-6 grid grid-cols-1 gap-x-10 gap-y-8 sm:grid-cols-2 lg:grid-cols-4">
        {groups.map((g) => (
          <div key={g.key}>
            <h3 className="border-b pb-2 text-sm font-semibold">{g.title}</h3>
            <ul className="mt-1">
              {g.types.map((t) => (
                <li key={t.code}>
                  <Link
                    to={hrefFor(t.code)}
                    className="-mx-2 flex items-baseline justify-between gap-3 rounded-md px-2 py-1.5 text-[15px] text-body transition-colors hover:bg-accent hover:text-foreground"
                  >
                    <span className="min-w-0 truncate">{t.name}</span>
                    <span className="shrink-0 text-xs text-muted-foreground tabular-nums">{t.count}</span>
                  </Link>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>
    </section>
  );
}
