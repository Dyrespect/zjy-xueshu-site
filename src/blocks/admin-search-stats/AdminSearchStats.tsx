import type { ReactNode } from "react";
import { Link } from "react-router";

import { Skeleton } from "@/components/ui/skeleton";
import type { SearchStats } from "@/lib/figures-types";

export interface AdminSearchStatsProps {
  stats: SearchStats | null;
  searchHref: (q: string) => string;
}

function when(iso: string) {
  return new Date(iso).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="mt-10">
      <h2 className="text-base font-semibold">{title}</h2>
      <div className="mt-3">{children}</div>
    </section>
  );
}

/** 搜索统计：今天 / 7 天搜索次数、库里没有的词排行、被点最多的图、最近的搜索 */
export function AdminSearchStats({ stats, searchHref }: AdminSearchStatsProps) {
  if (!stats) {
    return (
      <div className="max-w-4xl" aria-busy="true">
        <Skeleton className="h-8 w-40" />
        <Skeleton className="mt-6 h-16 w-72" />
      </div>
    );
  }
  return (
    <div className="max-w-4xl">
      <h1 className="text-2xl font-semibold">搜索统计</h1>
      <div className="mt-6 flex gap-12">
        {[
          ["今天", stats.today],
          ["最近 7 天", stats.week],
        ].map(([label, n]) => (
          <div key={label}>
            <div className="text-3xl font-semibold text-foreground tabular-nums">{n}</div>
            <div className="mt-1 text-sm text-muted-foreground">{label}搜索次数</div>
          </div>
        ))}
      </div>

      <Section title="库里没有的词（最近 30 天）">
        {stats.zero_words.length ? (
          <ol className="flex flex-col">
            {stats.zero_words.map((z) => (
              <li key={z.word} className="flex max-w-md items-baseline justify-between border-b py-2 text-[15px] last:border-b-0">
                <span className="text-foreground">{z.word}</span>
                <span className="text-sm text-muted-foreground tabular-nums">{z.n} 次</span>
              </li>
            ))}
          </ol>
        ) : (
          <p className="text-[15px] text-body">还没有。</p>
        )}
      </Section>

      <Section title="被点最多的图（最近 30 天）">
        {stats.top_clicked.length ? (
          <div className="grid grid-cols-3 gap-3 sm:grid-cols-6">
            {stats.top_clicked.map((f) => (
              <a key={f.id} href={`/figure/${f.id}`} target="_blank" rel="noreferrer" className="flex flex-col gap-1.5" title={f.title}>
                <img src={f.thumb_url} alt={f.title} className="aspect-[4/3] w-full rounded-md border bg-card object-contain p-1" />
                <span className="text-xs text-muted-foreground tabular-nums">点了 {f.n} 次</span>
              </a>
            ))}
          </div>
        ) : (
          <p className="text-[15px] text-body">还没有。</p>
        )}
      </Section>

      <Section title="最近的搜索">
        {stats.recent.length ? (
          <ul className="flex flex-col">
            {stats.recent.map((s) => (
              <li key={s.id} className="flex flex-wrap items-baseline gap-x-4 gap-y-0.5 border-b py-2.5 text-sm last:border-b-0">
                <time className="w-24 shrink-0 text-muted-foreground" dateTime={s.created_at}>
                  {when(s.created_at)}
                </time>
                <Link to={searchHref(s.query)} target="_blank" className="min-w-0 flex-1 text-foreground hover:text-primary">
                  {s.query}
                </Link>
                <span className="text-muted-foreground">
                  {s.code_name} · {s.total} 张
                  {s.zero_words.length ? ` · 库里没有「${s.zero_words.join("」「")}」` : ""}
                </span>
              </li>
            ))}
          </ul>
        ) : (
          <p className="text-[15px] text-body">还没有。</p>
        )}
      </Section>
    </div>
  );
}
