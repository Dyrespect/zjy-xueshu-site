import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { SiteLink } from "@/components/site-link";
import { FigureGrid, FigureGridSkeleton } from "@/blocks/figure-card";
import type { FigureCard, SearchResult, TypeRef } from "@/lib/figures-types";

const ANY = "任意";
const TYPE_GROUPS: [string, string[]][] = [
  ["为什么做", ["W"]],
  ["研究设计", ["P", "S", "D"]],
  ["分析", ["A"]],
  ["结果", ["R"]],
];

export interface SearchResultsProps {
  result: SearchResult | null;
  loading?: boolean;
  error?: string;
  /** 图型下拉的全部选项 */
  types: TypeRef[];
  /** 最后一行的导流入口（官网、下单页，模块 L）；不给 = 不显示 */
  cta?: { siteUrl: string; orderUrl: string; onClick?: (target: "site" | "order") => void };
  onChangeType: (code: string) => void;
  hrefFor: (card: FigureCard) => string;
  stateFor?: (card: FigureCard) => unknown;
  onOpen?: (card: FigureCard, position: number, lane: string) => void;
  onRequest: () => void;
  onRetry?: () => void;
}

function TypeSelect({ value, types, onChange }: { value: string; types: TypeRef[]; onChange: (c: string) => void }) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger size="sm" aria-label="图型" className="min-w-0 font-medium text-foreground">
        <SelectValue />
      </SelectTrigger>
      <SelectContent position="popper" align="start" className="max-h-[min(70vh,28rem)]">
        <SelectItem value={ANY}>不限图型</SelectItem>
        {TYPE_GROUPS.map(([title, prefixes]) => (
          <SelectGroup key={title}>
            <SelectLabel>{title}</SelectLabel>
            {types
              .filter((t) => prefixes.some((p) => t.code.startsWith(p)))
              .map((t) => (
                <SelectItem key={t.code} value={t.code}>
                  {t.name}
                </SelectItem>
              ))}
          </SelectGroup>
        ))}
      </SelectContent>
    </Select>
  );
}

function Loading() {
  return (
    <div aria-busy="true" aria-label="正在找">
      <Skeleton className="h-8 w-64" />
      <Skeleton className="mt-10 h-6 w-40" />
      <div className="mt-4">
        <FigureGridSkeleton count={8} />
      </div>
    </div>
  );
}

function quoteAll(words: string[]) {
  return words.map((w) => `「${w}」`).join("");
}

export function SearchResults({
  result,
  loading,
  error,
  types,
  cta,
  onChangeType,
  hrefFor,
  stateFor,
  onOpen,
  onRequest,
  onRetry,
}: SearchResultsProps) {
  if (loading) return <Loading />;
  if (error) {
    return (
      <div className="py-10">
        <p className="text-[15px] text-foreground">{error}</p>
        {onRetry ? (
          <Button variant="outline" className="mt-4" onClick={onRetry}>
            再试一次
          </Button>
        ) : null}
      </div>
    );
  }
  if (!result) return null;

  const lead = result.overridden ? "按这个图型找" : result.guess ? "看起来你要画的是" : "没猜出要画哪类图，先不限图型找";
  let position = 0;

  return (
    <div>
      <div className="flex flex-wrap items-center gap-x-2.5 gap-y-2 text-[15px]">
        <span className="text-body">{lead}</span>
        <TypeSelect value={result.code} types={types} onChange={onChangeType} />
      </div>

      {result.zero_words.length > 0 ? (
        <p className="mt-5 text-[15px] font-medium text-foreground">
          库里没有{quoteAll(result.zero_words)}的图，下面是相近的。
        </p>
      ) : null}

      {result.total === 0 ? (
        <div className="mt-10">
          <h2 className="text-lg font-semibold">没找到和「{result.query}」相近的图</h2>
          <p className="mt-2 text-[15px] text-body">换个说法，或者告诉我们你要画什么，我们去补。</p>
          <Button className="mt-5" onClick={onRequest}>
            告诉我们你要画什么
          </Button>
        </div>
      ) : (
        <div className="mt-8 flex flex-col gap-12">
          {result.groups.map((g) => {
            const start = position;
            position += g.cards.length;
            return (
              <section key={g.key} aria-labelledby={`group-${g.key}`}>
                <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
                  <h2 id={`group-${g.key}`} className="text-lg font-semibold">
                    {g.title}
                  </h2>
                  {g.learn ? <span className="text-sm text-muted-foreground">{g.learn}</span> : null}
                </div>
                <div className="mt-4">
                  <FigureGrid
                    cards={g.cards}
                    hrefFor={hrefFor}
                    stateFor={stateFor}
                    onOpen={onOpen ? (c, i) => onOpen(c, start + i, g.key) : undefined}
                  />
                </div>
              </section>
            );
          })}
        </div>
      )}

      {result.total > 0 ? (
        <section className="mt-16 border-t pt-10">
          <h2 className="text-lg font-semibold">没找到想要的？告诉我们你要画什么</h2>
          <Button variant="outline" className="mt-4" onClick={onRequest}>
            提需求
          </Button>
        </section>
      ) : null}

      {cta ? (
        <p className="mt-10 text-[15px] text-body">
          要把这类图做进你的汇报 PPT？{" "}
          <SiteLink href={cta.siteUrl} onClick={() => cta.onClick?.("site")} className="text-primary hover:text-primary-hover">
            看看我们怎么做
          </SiteLink>
          <span className="mx-2 text-muted-foreground">·</span>
          <SiteLink href={cta.orderUrl} onClick={() => cta.onClick?.("order")} className="font-medium text-primary hover:text-primary-hover">
            直接下单
          </SiteLink>
        </p>
      ) : null}
    </div>
  );
}
