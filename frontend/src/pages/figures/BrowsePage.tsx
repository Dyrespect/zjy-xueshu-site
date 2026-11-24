import { useEffect, useState } from "react";
import { Link, useParams } from "react-router";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { FigureGrid, FigureGridSkeleton } from "@/blocks/figure-card";
import { fetchBrowse } from "@/lib/figures";
import type { BrowsePage as Page, FigureCard } from "@/lib/figures-types";

import { figureHref, useTitle } from "./gallery-context";

const PAGE = 40;

export default function BrowsePage() {
  const { code = "" } = useParams();
  const [page, setPage] = useState<Page | null>(null);
  const [cards, setCards] = useState<FigureCard[]>([]);
  const [error, setError] = useState("");
  const [more, setMore] = useState(false);
  useTitle(page?.name);

  useEffect(() => {
    let alive = true;
    setPage(null);
    setCards([]);
    setError("");
    fetchBrowse(code, 0, PAGE).then(
      (p) => {
        if (!alive) return;
        setPage(p);
        setCards(p.cards);
      },
      (e: Error) => alive && setError(e.message),
    );
    return () => {
      alive = false;
    };
  }, [code]);

  async function loadMore() {
    setMore(true);
    try {
      const p = await fetchBrowse(code, cards.length, PAGE);
      setCards((prev) => [...prev, ...p.cards]);
    } finally {
      setMore(false);
    }
  }

  return (
    <main className="mx-auto max-w-6xl px-4 pt-6 pb-16 sm:px-6 sm:pt-8">
      <nav aria-label="位置" className="flex items-center gap-1.5 text-sm text-muted-foreground">
        <Link to="/" className="hover:text-foreground">
          首页
        </Link>
        <span aria-hidden>/</span>
        <span>{page?.group_title ?? "图型"}</span>
      </nav>
      {error ? (
        <p className="py-10 text-[15px] text-foreground">{error}</p>
      ) : page ? (
        <>
          <h1 className="mt-3 text-2xl font-semibold">{page.name}</h1>
          <p className="mt-1 text-sm text-muted-foreground">库里有 {page.total} 张，好刊在前、新的在前</p>
          <div className="mt-6">
            <FigureGrid cards={cards} hrefFor={(c) => figureHref(c.id)} />
          </div>
          {cards.length < page.total ? (
            <div className="mt-8 flex justify-center">
              <Button variant="outline" onClick={loadMore} disabled={more}>
                {more ? "正在加载…" : `再看 ${Math.min(PAGE, page.total - cards.length)} 张`}
              </Button>
            </div>
          ) : null}
        </>
      ) : (
        <div aria-busy="true">
          <Skeleton className="mt-3 h-8 w-48" />
          <Skeleton className="mt-2 h-4 w-32" />
          <div className="mt-6">
            <FigureGridSkeleton count={12} />
          </div>
        </div>
      )}
    </main>
  );
}
