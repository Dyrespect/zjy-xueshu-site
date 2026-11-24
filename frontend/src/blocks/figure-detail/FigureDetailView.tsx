import { useState, type ReactNode } from "react";
import { Link } from "react-router";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { FigureGrid, FigureGridSkeleton } from "@/blocks/figure-card";
import type { FigureCard, FigureDetail } from "@/lib/figures-types";
import { cn } from "@/lib/utils";

export interface FigureDetailViewProps {
  detail: FigureDetail | null;
  loading?: boolean;
  error?: string;
  /** 更多类似的；null = 还在取 */
  similar: FigureCard[] | null;
  searchHref: (word: string) => string;
  typeHref: (code: string) => string;
  cardHref: (card: FigureCard) => string;
  /** 点「更多类似的」时带过去的路由 state（把搜索上下文一路带着） */
  cardState?: unknown;
  onFeedback: () => void;
  onSubmitFigure: () => void;
  onAllLibrary: () => void;
}

const LONG_CAPTION = 260;

function Label({ children }: { children: ReactNode }) {
  return <h2 className="text-xs font-medium tracking-wide text-muted-foreground">{children}</h2>;
}

function WordLink({ to, children }: { to: string; children: ReactNode }) {
  return (
    <Link
      to={to}
      className="rounded-md bg-card px-2 py-0.5 text-[13px] text-body transition-colors hover:bg-accent hover:text-foreground"
    >
      {children}
    </Link>
  );
}

async function copy(text: string) {
  try {
    await navigator.clipboard.writeText(text);
    toast.success("出处复制好了，可以贴进 PPT 的图注");
  } catch {
    toast.error("没复制成功，可以手动选中下面这行复制");
  }
}

function Loading() {
  return (
    <div className="grid gap-8 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] lg:gap-12" aria-busy="true">
      <Skeleton className="aspect-[4/3] w-full" />
      <div className="flex flex-col gap-3">
        <Skeleton className="h-8 w-4/5" />
        <Skeleton className="h-4 w-1/2" />
        <Skeleton className="mt-6 h-4 w-full" />
        <Skeleton className="h-4 w-11/12" />
        <Skeleton className="h-4 w-3/4" />
      </div>
    </div>
  );
}

export function FigureDetailView({
  detail,
  loading,
  error,
  similar,
  searchHref,
  typeHref,
  cardHref,
  cardState,
  onFeedback,
  onSubmitFigure,
  onAllLibrary,
}: FigureDetailViewProps) {
  const [imgLoaded, setImgLoaded] = useState(false);
  const [expanded, setExpanded] = useState(false);

  if (loading) return <Loading />;
  if (error || !detail) return <p className="py-10 text-[15px] text-foreground">{error || "没有这张图"}</p>;

  const d = detail;
  const meta = [`${d.journal}${d.year ? ` ${d.year}` : ""}`, d.tier].filter(Boolean).join(" · ");
  const longCaption = d.caption.length > LONG_CAPTION;

  return (
    <div>
      <nav aria-label="位置" className="flex items-center gap-1.5 text-sm text-muted-foreground">
        <Link to="/" className="hover:text-foreground">
          首页
        </Link>
        <span aria-hidden>/</span>
        <Link to={typeHref(d.type_code)} className="hover:text-foreground">
          {d.type_name}
        </Link>
      </nav>

      <div className="mt-4 grid gap-8 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] lg:gap-12">
        <div
          className={cn(
            "relative flex items-center justify-center self-start rounded-lg border bg-card p-3 sm:p-5",
            !imgLoaded && "min-h-64",
          )}
        >
          {!imgLoaded ? <Skeleton className="absolute inset-3 sm:inset-5" /> : null}
          <img
            key={d.preview_url}
            src={d.preview_url}
            alt={d.title}
            onLoad={() => setImgLoaded(true)}
            className={cn("relative max-h-[72vh] w-auto max-w-full object-contain", !imgLoaded && "opacity-0")}
          />
        </div>

        <div className="min-w-0">
          <h1 className="text-2xl leading-snug font-semibold">{d.title}</h1>
          {d.credits?.length ? <p className="mt-1 text-xs text-muted-foreground">{d.credits.join("；")}</p> : null}
          <p className="mt-2 text-sm text-muted-foreground">{meta}</p>

          <section className="mt-7">
            <Label>出处</Label>
            <p className="mt-1.5 text-[15px] leading-relaxed text-body">
              {d.link ? (
                <a href={d.link} target="_blank" rel="noopener noreferrer" className="text-primary hover:text-primary-hover">
                  {d.paper_title}
                </a>
              ) : (
                d.paper_title
              )}
            </p>
            {d.authors ? <p className="mt-1 text-sm text-muted-foreground">{d.authors}</p> : null}
            {d.doi ? <p className="mt-1 text-sm break-all text-muted-foreground">DOI {d.doi}</p> : null}
            <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
              <Button variant="outline" size="sm" onClick={() => copy(d.cite)}>
                复制出处
              </Button>
              <span className="text-xs text-muted-foreground">图片版权归原作者和期刊，仅供学习参考</span>
            </div>
          </section>

          {d.caption ? (
            <section className="mt-7">
              <Label>原文图注</Label>
              <p
                className={cn(
                  "mt-1.5 text-sm leading-relaxed break-words whitespace-pre-line text-body",
                  longCaption && !expanded && "line-clamp-6",
                )}
              >
                {d.caption}
              </p>
              {longCaption ? (
                <button
                  type="button"
                  onClick={() => setExpanded((v) => !v)}
                  className="mt-1 text-sm text-muted-foreground hover:text-foreground"
                >
                  {expanded ? "收起" : "展开全部"}
                </button>
              ) : null}
            </section>
          ) : null}

          <section className="mt-7">
            <Label>这张图的标签（点一个词按它找）</Label>
            <dl className="mt-2.5 grid grid-cols-[auto_minmax(0,1fr)] items-baseline gap-x-4 gap-y-2.5">
              <dt className="text-sm text-muted-foreground">图型</dt>
              <dd className="flex flex-wrap gap-1.5">
                {d.types.map((t) => (
                  <WordLink key={t.code} to={typeHref(t.code)}>
                    {t.name}
                  </WordLink>
                ))}
              </dd>
              {d.tags.map((t) => (
                <div key={t.label} className="contents">
                  <dt className="text-sm whitespace-nowrap text-muted-foreground">{t.label}</dt>
                  <dd className="flex flex-wrap gap-1.5">
                    {t.words.map((w) => (
                      <WordLink key={w} to={searchHref(w)}>
                        {w}
                      </WordLink>
                    ))}
                  </dd>
                </div>
              ))}
            </dl>
          </section>

          <div className="mt-8 flex flex-wrap gap-x-5 gap-y-2 border-t pt-5 text-sm">
            <button type="button" onClick={onFeedback} className="text-muted-foreground hover:text-foreground">
              标签不对 / 这张不相关
            </button>
            <button type="button" onClick={onSubmitFigure} className="text-muted-foreground hover:text-foreground">
              我有更好的同类图
            </button>
            <button type="button" onClick={onAllLibrary} className="text-muted-foreground hover:text-foreground">
              要全部图库？
            </button>
          </div>
        </div>
      </div>

      <section className="mt-16" aria-labelledby="similar-title">
        <h2 id="similar-title" className="text-lg font-semibold">
          更多类似的
        </h2>
        <div className="mt-4">
          {similar ? <FigureGrid cards={similar} hrefFor={cardHref} stateFor={() => cardState} /> : <FigureGridSkeleton count={8} />}
        </div>
      </section>
    </div>
  );
}
