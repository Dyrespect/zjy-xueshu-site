import { useCallback, useEffect, useState } from "react";
import { Navigate, useNavigate, useSearchParams } from "react-router";

import { FigureSearchBox } from "@/blocks/figure-search-box";
import { SearchResults } from "@/blocks/search-results";
import { loadSearch, logClick } from "@/blocks/search-results/load";
import type { SearchContext, SearchResult } from "@/lib/figures-types";

import { figureHref, orderHref, searchHref, useGallery, useTitle } from "./gallery-context";

type State = { status: "loading" } | { status: "done"; result: SearchResult } | { status: "error"; message: string };

export default function SearchPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const { site, map, openRequest, trackCta } = useGallery();
  const q = (params.get("q") ?? "").trim();
  const code = params.get("code");
  const [state, setState] = useState<State>({ status: "loading" });
  const [attempt, setAttempt] = useState(0);
  useTitle(q || undefined);

  useEffect(() => {
    if (!q) return;
    let alive = true;
    setState({ status: "loading" });
    loadSearch(q, code).then(
      (result) => alive && setState({ status: "done", result }),
      (e: Error) => alive && setState({ status: "error", message: e.message || "没找成，请稍后再试" }),
    );
    return () => {
      alive = false;
    };
  }, [q, code, attempt]);

  const result = state.status === "done" ? state.result : null;
  const ctx: SearchContext = { searchId: result?.search_id ?? null, query: q };
  const retry = useCallback(() => setAttempt((n) => n + 1), []);

  if (!q) return <Navigate to="/" replace />;

  return (
    <main className="mx-auto max-w-6xl px-4 pt-6 pb-16 sm:px-6 sm:pt-8">
      <div className="max-w-3xl">
        <FigureSearchBox size="compact" defaultValue={q} onSubmit={(nq) => navigate(searchHref(nq))} />
      </div>
      <div className="mt-6">
        <SearchResults
          result={result}
          loading={state.status === "loading"}
          error={state.status === "error" ? state.message : undefined}
          onRetry={retry}
          types={site?.types ?? []}
          cta={map ? { siteUrl: map.cta.site_url, orderUrl: orderHref(map, "results"), onClick: (t) => trackCta("results", t) } : undefined}
          onChangeType={(c) => navigate(searchHref(q, c))}
          hrefFor={(c) => figureHref(c.id)}
          stateFor={() => ctx}
          onOpen={(c, position, lane) => logClick(ctx.searchId, c.id, position, lane)}
          onRequest={() => openRequest(ctx)}
        />
      </div>
    </main>
  );
}
