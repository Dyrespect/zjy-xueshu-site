import { Link } from "react-router";

import { Skeleton } from "@/components/ui/skeleton";
import type { FigureCard as Card } from "@/lib/figures-types";
import { cn } from "@/lib/utils";

export interface FigureCardProps {
  card: Card;
  /** 点卡片去哪（详情页地址） */
  href: string;
  /** 跳转时带过去的路由 state（搜索上下文） */
  state?: unknown;
  onOpen?: () => void;
  className?: string;
}

/** 一张图：缩略图、讲的是什么、期刊和年份、图型和期刊档。整张卡片可点，不放按钮。 */
export function FigureCard({ card, href, state, onOpen, className }: FigureCardProps) {
  const meta = [card.type_name, card.tier].filter(Boolean).join(" · ");
  return (
    <Link
      to={href}
      state={state}
      onClick={onOpen}
      className={cn(
        "group flex min-w-0 flex-col overflow-hidden rounded-lg border bg-background transition-colors hover:border-ring/50 focus-visible:ring-[3px] focus-visible:ring-ring/40 focus-visible:outline-none",
        className,
      )}
    >
      <div className="aspect-[4/3] min-h-0 overflow-hidden bg-card p-2.5">
        <img
          src={card.thumb_url}
          alt={card.title}
          loading="lazy"
          decoding="async"
          className="h-full w-full object-contain"
        />
      </div>
      <div className="flex flex-1 flex-col gap-1 border-t px-3 pt-2.5 pb-3">
        <div className="line-clamp-2 text-sm leading-snug font-medium text-foreground">{card.title}</div>
        <div className="truncate text-xs text-muted-foreground">
          {card.journal}
          {card.year ? ` ${card.year}` : ""}
        </div>
        {meta ? <div className="truncate text-xs text-muted-foreground">{meta}</div> : null}
      </div>
    </Link>
  );
}

export interface FigureGridProps {
  cards: Card[];
  hrefFor: (card: Card) => string;
  stateFor?: (card: Card, index: number) => unknown;
  onOpen?: (card: Card, index: number) => void;
}

export function FigureGrid({ cards, hrefFor, stateFor, onOpen }: FigureGridProps) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 lg:grid-cols-4">
      {cards.map((c, i) => (
        <FigureCard
          key={c.id}
          card={c}
          href={hrefFor(c)}
          state={stateFor?.(c, i)}
          onOpen={onOpen ? () => onOpen(c, i) : undefined}
        />
      ))}
    </div>
  );
}

/** 加载中：跟真卡片一样大的灰块 */
export function FigureGridSkeleton({ count = 8 }: { count?: number }) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 sm:gap-4 lg:grid-cols-4" aria-hidden>
      {Array.from({ length: count }, (_, i) => (
        <div key={i} className="overflow-hidden rounded-lg border">
          <Skeleton className="aspect-[4/3] rounded-none" />
          <div className="flex flex-col gap-2 px-3 pt-3 pb-3.5">
            <Skeleton className="h-3.5 w-11/12" />
            <Skeleton className="h-3 w-2/3" />
          </div>
        </div>
      ))}
    </div>
  );
}
