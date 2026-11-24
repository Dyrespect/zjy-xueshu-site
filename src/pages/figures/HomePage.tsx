import { useEffect, useState } from "react";
import { useNavigate } from "react-router";

import { Skeleton } from "@/components/ui/skeleton";
import { FigureSearchBox } from "@/blocks/figure-search-box";
import { FigureTypeIndex } from "@/blocks/figure-type-index";
import { PopularChips } from "@/blocks/popular-chips";
import { fetchHome } from "@/lib/figures";
import type { HomeInfo } from "@/lib/figures-types";

import { searchHref, typeHref, useTitle } from "./gallery-context";

export default function HomePage() {
  useTitle();
  const navigate = useNavigate();
  const [home, setHome] = useState<HomeInfo | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    fetchHome().then(setHome, () => setFailed(true));
  }, []);

  return (
    <main>
      <section className="mx-auto flex max-w-3xl flex-col items-center px-4 pt-[12vh] pb-20 sm:px-6 sm:pt-[17vh]">
        <h1 className="text-center text-[28px] leading-tight font-semibold tracking-tight sm:text-[40px]">
          <span className="inline-block">心理学好刊里的图，</span>
          <span className="inline-block">按你要画的找</span>
        </h1>
        <div className="mt-8 w-full sm:mt-10">
          <FigureSearchBox autoFocus onSubmit={(q) => navigate(searchHref(q))} />
        </div>
        <div className="mt-5 min-h-8 w-full">
          {home ? <PopularChips chips={home.popular} hrefFor={(c) => searchHref(c.query)} className="justify-center" /> : null}
        </div>
      </section>

      <div className="mx-auto max-w-6xl px-4 pb-16 sm:px-6">
        {home ? (
          <FigureTypeIndex groups={home.groups} hrefFor={typeHref} />
        ) : failed ? (
          <p className="text-[15px] text-body">图库暂时打不开，请稍后再试。</p>
        ) : (
          <div aria-busy="true" className="grid grid-cols-1 gap-8 sm:grid-cols-2 lg:grid-cols-4">
            {Array.from({ length: 4 }, (_, i) => (
              <div key={i} className="flex flex-col gap-3">
                <Skeleton className="h-5 w-20" />
                {Array.from({ length: 6 }, (_, j) => (
                  <Skeleton key={j} className="h-4 w-full" />
                ))}
              </div>
            ))}
          </div>
        )}
        {home ? (
          <p className="mt-14 text-sm text-muted-foreground">
            库里共 {home.total.toLocaleString("zh-CN")} 张图，来自 {home.journals} 本期刊
          </p>
        ) : null}
      </div>
    </main>
  );
}
