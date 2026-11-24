import { Paperclip, Plus, X, ZoomIn } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import type { ProofRound, RevisionDraft } from "@/lib/delivery-types";
import { cn } from "@/lib/utils";

export interface ProofViewerProps {
  /** 发布过的每一版（旧的在前），只有最新一版能标修改 */
  rounds: ProofRound[];
  canMark: boolean;
  drafts: RevisionDraft[];
  wholeMax: number;
  fileMaxMb: number;
  onDraftsChange: (next: RevisionDraft[]) => void;
  /** 没有水印图可看时（已交付后用剩下的那轮）按页码提：共几页 */
  pageCount?: number;
  /** 看到了第几页（最新一版里看到的最大页码） */
  onSeen?: (round: number, maxPage: number) => void;
}

let seq = 0;
const newKey = () => `d${++seq}`;

function NoteEditor({
  draft, fileMaxMb, label, onChange, onRemove,
}: { draft: RevisionDraft; fileMaxMb: number; label: string; onChange: (d: RevisionDraft) => void; onRemove: () => void }) {
  const fileRef = useRef<HTMLInputElement>(null);
  const [tooBig, setTooBig] = useState("");
  return (
    <div className="mt-3 rounded-lg border border-primary/40 bg-background p-3">
      <textarea
        autoFocus={!draft.text}
        value={draft.text}
        onChange={(e) => onChange({ ...draft, text: e.target.value })}
        aria-label={label}
        placeholder="改成什么？比如：时间轴太挤，1971—1972 那个点挪到下面一行"
        className="field-sizing-content min-h-20 w-full resize-none bg-transparent text-base leading-relaxed text-foreground outline-none placeholder:text-muted-foreground"
      />
      {draft.files.length ? (
        <ul className="mt-2 flex flex-col gap-1 text-sm">
          {draft.files.map((f, i) => (
            <li key={`${f.name}-${i}`} className="flex items-center gap-2 text-body">
              <Paperclip className="size-3.5 text-muted-foreground" />
              <span className="min-w-0 flex-1 truncate">{f.name}</span>
              <button type="button" aria-label="去掉这个附件" onClick={() => onChange({ ...draft, files: draft.files.filter((_, j) => j !== i) })}>
                <X className="size-4 text-muted-foreground" />
              </button>
            </li>
          ))}
        </ul>
      ) : null}
      {tooBig ? <p className="mt-2 text-sm text-destructive">{tooBig}</p> : null}
      <div className="mt-2 flex items-center gap-1">
        <input
          ref={fileRef}
          type="file"
          accept="image/*,.pdf"
          multiple
          className="hidden"
          data-testid="note-files"
          onChange={(e) => {
            const picked = Array.from(e.target.files ?? []);
            const ok = picked.filter((f) => f.size <= fileMaxMb * 1024 * 1024);
            setTooBig(ok.length < picked.length ? `单个附件不超过 ${fileMaxMb}MB` : "");
            onChange({ ...draft, files: [...draft.files, ...ok].slice(0, 5) });
            if (fileRef.current) fileRef.current.value = "";
          }}
        />
        <Button type="button" variant="ghost" size="sm" onClick={() => fileRef.current?.click()}>
          <Paperclip />
          附截图
        </Button>
        <Button type="button" variant="ghost" size="sm" className="ml-auto text-muted-foreground" onClick={onRemove}>
          不改了
        </Button>
      </div>
    </div>
  );
}

function PagePicker({ pageCount, taken, onPick }: { pageCount: number; taken: Set<number>; onPick: (page: number) => void }) {
  const free = Array.from({ length: pageCount }, (_, i) => i + 1).filter((n) => !taken.has(n));
  const [page, setPage] = useState<number>(free[0] ?? 1);
  if (!free.length) return null;
  const value = free.includes(page) ? page : free[0];
  return (
    <div className="mt-4 flex items-center gap-2">
      <select
        aria-label="第几页"
        value={value}
        onChange={(e) => setPage(Number(e.target.value))}
        className="h-9 rounded-md border border-input bg-background px-3 text-sm text-foreground"
      >
        {free.map((n) => (
          <option key={n} value={n}>
            第 {n} 页
          </option>
        ))}
      </select>
      <Button type="button" variant="outline" size="sm" onClick={() => onPick(value)}>
        这页要改
      </Button>
    </div>
  );
}

/** 水印版逐页看：每页一张整页图占满内容宽（点开看原大），图下「第 N 页 · 这页要改」，点了就在这页下面写；最后是整体意见。 */
export function ProofViewer({ rounds, canMark, drafts, wholeMax, fileMaxMb, onDraftsChange, pageCount = 0, onSeen }: ProofViewerProps) {
  const latest = rounds[rounds.length - 1];
  const [shown, setShown] = useState<number>(latest?.round ?? 1);
  const [zoom, setZoom] = useState<{ url: string; page: number } | null>(null);
  const round = rounds.find((r) => r.round === shown) ?? latest;
  const markable = canMark && round?.round === latest?.round;
  const byPage = useMemo(() => new Map(drafts.filter((d) => d.page != null).map((d) => [d.page as number, d])), [drafts]);
  const whole = drafts.filter((d) => d.page == null);
  const seen = useRef(0);
  const listRef = useRef<HTMLOListElement>(null);

  useEffect(() => setShown(latest?.round ?? 1), [latest?.round]);

  useEffect(() => {
    if (!onSeen || !latest || round?.round !== latest.round || !listRef.current || typeof IntersectionObserver === "undefined") return;
    const io = new IntersectionObserver((entries) => {
      for (const e of entries) {
        const p = Number((e.target as HTMLElement).dataset.page);
        if (e.isIntersecting && p > seen.current) {
          seen.current = p;
          onSeen(latest.round, p);
        }
      }
    }, { threshold: 0.4 });
    listRef.current.querySelectorAll("[data-page]").forEach((el) => io.observe(el));
    return () => io.disconnect();
  }, [latest, round, onSeen]);

  const put = (d: RevisionDraft) => onDraftsChange(drafts.some((x) => x.key === d.key) ? drafts.map((x) => (x.key === d.key ? d : x)) : [...drafts, d]);
  const drop = (key: string) => onDraftsChange(drafts.filter((x) => x.key !== key));
  const wholeBlock = (
    <div className="mt-12 border-t pt-6">
      <h3 className="text-base font-semibold text-foreground">整体意见</h3>
      <p className="mt-1 text-sm text-body">不落到某一页的写这里（比如配色、字号），最多 {wholeMax} 条；能落到某一页的，写到那一页下面更清楚。</p>
      {whole.map((d, i) => (
        <NoteEditor key={d.key} draft={d} fileMaxMb={fileMaxMb} label={`整体意见第 ${i + 1} 条`} onChange={put} onRemove={() => drop(d.key)} />
      ))}
      {whole.length < wholeMax ? (
        <Button type="button" variant="outline" size="sm" className="mt-3" onClick={() => put({ key: newKey(), page: null, text: "", files: [] })}>
          <Plus />
          加一条整体意见
        </Button>
      ) : null}
    </div>
  );

  if (!round) {
    if (!canMark || pageCount < 1) return null;
    const pages = drafts.filter((d) => d.page != null).sort((a, b) => (a.page ?? 0) - (b.page ?? 0));
    return (
      <section aria-label="按页码提修改" className="mt-8 border-t pt-6">
        <h2 className="text-lg font-semibold text-foreground">按页码提修改</h2>
        <p className="mt-1 text-sm text-body">页码 = 可编辑 PPT 的第几张（共 {pageCount} 页）。</p>
        <PagePicker pageCount={pageCount} taken={new Set(pages.map((d) => d.page as number))} onPick={(page) => put({ key: newKey(), page, text: "", files: [] })} />
        {pages.map((d) => (
          <div key={d.key} className="mt-4">
            <div className="text-sm font-medium text-foreground">第 {d.page} 页</div>
            <NoteEditor draft={d} fileMaxMb={fileMaxMb} label={`第 ${d.page} 页要改什么`} onChange={put} onRemove={() => drop(d.key)} />
          </div>
        ))}
        {wholeBlock}
      </section>
    );
  }

  return (
    <section aria-label="水印版" className="mt-8">
      <div className="flex flex-wrap items-end justify-between gap-3 border-t pt-6">
        <div>
          <h2 className="text-lg font-semibold text-foreground">第 {round.round} 版水印版</h2>
          <p className="mt-1 text-sm text-body">每页都是完整大小的图，点图看原大；铺了水印、不能编辑，确认收货后发可编辑的 PPT 和讲稿。</p>
        </div>
        {rounds.length > 1 ? (
          <div className="flex gap-1" role="tablist" aria-label="看哪一版">
            {[...rounds].reverse().map((r) => (
              <button
                key={r.round}
                type="button"
                role="tab"
                aria-selected={r.round === round.round}
                onClick={() => setShown(r.round)}
                className={cn("h-8 rounded-md border px-3 text-sm", r.round === round.round ? "border-foreground/30 bg-accent font-medium text-foreground" : "text-body hover:bg-accent")}
              >
                第 {r.round} 版{r.round === latest.round ? "（最新）" : ""}
              </button>
            ))}
          </div>
        ) : null}
      </div>

      <ol ref={listRef} className="mt-6 flex flex-col gap-10">
        {round.pages.map((p) => {
          const draft = markable ? byPage.get(p.page) : undefined;
          return (
            <li key={`${round.round}-${p.page}`} id={`p-${p.page}`} data-page={p.page}>
              <figure>
                <button
                  type="button"
                  className="group relative block w-full cursor-zoom-in"
                  aria-label={`看第 ${p.page} 页原大`}
                  onClick={() => p.url && setZoom({ url: p.url, page: p.page })}
                >
                  {p.url ? (
                    <img
                      src={p.url}
                      alt={`第 ${p.page} 页（水印版）`}
                      loading={p.page <= 2 ? "eager" : "lazy"}
                      width={1920}
                      height={1138}
                      className={cn("block h-auto w-full rounded-sm border bg-card shadow-figure", draft ? "border-primary" : "")}
                    />
                  ) : (
                    <div className="flex aspect-[1920/1138] w-full items-center justify-center rounded-sm border bg-card text-sm text-muted-foreground shadow-figure">
                      第 {p.page} 页（示例）
                    </div>
                  )}
                  <span className="absolute top-2 right-2 hidden rounded-md border bg-background p-1.5 text-body group-hover:block">
                    <ZoomIn className="size-4" />
                  </span>
                </button>
                <figcaption className="mt-3 flex items-center justify-between gap-3">
                  <span className="text-sm text-body tabular-nums">第 {p.page} 页</span>
                  {markable && !draft ? (
                    <Button type="button" variant="outline" size="sm" onClick={() => put({ key: newKey(), page: p.page, text: "", files: [] })}>
                      这页要改
                    </Button>
                  ) : draft ? (
                    <span className="text-sm font-medium text-primary">这页要改</span>
                  ) : null}
                </figcaption>
              </figure>
              {draft ? (
                <NoteEditor draft={draft} fileMaxMb={fileMaxMb} label={`第 ${p.page} 页要改什么`} onChange={put} onRemove={() => drop(draft.key)} />
              ) : null}
            </li>
          );
        })}
      </ol>

      {markable ? wholeBlock : null}

      <Dialog open={zoom != null} onOpenChange={(o) => !o && setZoom(null)}>
        <DialogContent className="h-dvh w-screen max-w-none gap-0 rounded-none border-0 p-0 sm:max-w-none">
          <DialogTitle className="sr-only">第 {zoom?.page} 页原大</DialogTitle>
          <div className="h-full w-full overflow-auto bg-card">
            {zoom ? <img src={zoom.url} alt={`第 ${zoom.page} 页原大（水印版）`} className="block max-w-none" width={1920} /> : null}
          </div>
        </DialogContent>
      </Dialog>
    </section>
  );
}
