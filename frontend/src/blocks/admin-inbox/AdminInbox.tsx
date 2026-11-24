import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import type { InboxItem, InboxKind, InboxList } from "@/lib/figures-types";
import { cn } from "@/lib/utils";

export type InboxFilter = "all" | "new" | "done";

export interface AdminInboxProps {
  kind: InboxKind;
  title: string;
  data: InboxList | null;
  filter: InboxFilter;
  onFilter: (f: InboxFilter) => void;
  onUpdate: (id: number, body: { status?: "new" | "done"; admin_note?: string }) => Promise<InboxItem>;
  /** 审核（标签反馈、投图）：通过 = 网站马上用新标签 / 收进下一版图库；不给就不显示这两个按钮 */
  onCurate?: (id: number, decision: "approve" | "reject") => Promise<void>;
}

const DECISION: Record<string, string> = { approved: "已通过", rejected: "没通过", hidden: "已下架" };

function when(iso: string) {
  return new Date(iso).toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function Line({ label, value }: { label: string; value?: string }) {
  if (!value) return null;
  return (
    <div className="flex gap-2 text-sm">
      <span className="shrink-0 text-muted-foreground">{label}</span>
      <span className="min-w-0 break-words text-body">{value}</span>
    </div>
  );
}

function mainText(kind: InboxKind, it: InboxItem) {
  if (kind === "feedback") return [it.reason, it.note].filter(Boolean).join("：");
  if (kind === "requests") return it.want;
  if (kind === "submissions") return it.source;
  return it.content;
}

function Row({
  kind,
  item,
  onUpdate,
  onCurate,
}: {
  kind: InboxKind;
  item: InboxItem;
  onUpdate: AdminInboxProps["onUpdate"];
  onCurate?: AdminInboxProps["onCurate"];
}) {
  const [it, setIt] = useState(item);
  const [note, setNote] = useState(item.admin_note);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    setIt(item);
    setNote(item.admin_note);
  }, [item]);

  async function update(body: { status?: "new" | "done"; admin_note?: string }) {
    setBusy(true);
    try {
      const next = await onUpdate(it.id, body);
      setIt(next);
      setNote(next.admin_note);
    } finally {
      setBusy(false);
    }
  }

  const pic = it.figure?.thumb_url || it.image_url;
  const picHref = it.figure ? `/figure/${it.figure.id}` : it.image_url;
  return (
    <li className="flex gap-4 border-b py-5 last:border-b-0">
      {pic ? (
        <a href={picHref} target="_blank" rel="noreferrer" className="shrink-0">
          <img src={pic} alt={it.figure?.title ?? "上传的图"} className="size-20 rounded-md border bg-card object-contain p-1" />
        </a>
      ) : null}
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-3 text-xs text-muted-foreground">
          <time dateTime={it.created_at}>{when(it.created_at)}</time>
          <span className={cn(it.status === "new" && "font-medium text-foreground")}>
            {it.status === "new" ? "没处理" : `处理了${it.handled_at ? ` · ${when(it.handled_at)}` : ""}`}
          </span>
        </div>
        <p className="mt-1.5 text-[15px] break-words text-foreground">{mainText(kind, it)}</p>
        <div className="mt-1.5 flex flex-col gap-0.5">
          {it.figure ? <Line label="图" value={`#${it.figure.id} ${it.figure.title}`} /> : null}
          <Line label="搜的" value={it.query} />
          <Line label="方法" value={it.method} />
          <Line label="为什么好" value={kind === "submissions" ? it.reason : undefined} />
          <Line label="改成" value={it.proposed?.what} />
          <Line label="署名" value={it.credit} />
          <Line label="审核" value={it.decision && it.decision !== "new" ? DECISION[it.decision] : undefined} />
          <Line label="联系" value={it.contact} />
          <Line label="页面" value={it.page} />
        </div>
        <form
          className="mt-3 flex max-w-xl items-center gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            update({ admin_note: note });
          }}
        >
          <Input value={note} onChange={(e) => setNote(e.target.value)} placeholder="写一句备注" maxLength={500} className="h-8" aria-label="备注" />
          {note !== it.admin_note ? (
            <Button type="submit" size="sm" variant="outline" disabled={busy}>
              保存
            </Button>
          ) : null}
        </form>
      </div>
      <div className="flex shrink-0 flex-col items-end gap-2">
        {onCurate && it.decision === "new" ? (
          <div className="flex gap-2">
            <Button
              size="sm"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  await onCurate(it.id, "approve");
                  setIt({ ...it, decision: "approved", status: "done" });
                } finally {
                  setBusy(false);
                }
              }}
            >
              {kind === "submissions" ? "收进下一版" : "通过，用新标签"}
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={async () => {
                setBusy(true);
                try {
                  await onCurate(it.id, "reject");
                  setIt({ ...it, decision: "rejected", status: "done" });
                } finally {
                  setBusy(false);
                }
              }}
            >
              不通过
            </Button>
          </div>
        ) : null}
        {it.status === "new" ? (
          <Button size="sm" variant="outline" disabled={busy} onClick={() => update({ status: "done" })}>
            标为处理了
          </Button>
        ) : (
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => update({ status: "new" })} className="text-muted-foreground">
            改回没处理
          </Button>
        )}
      </div>
    </li>
  );
}

/** 后台的一个收件列表（标签反馈 / 需求 / 投图 / 网站意见） */
export function AdminInbox({ kind, title, data, filter, onFilter, onUpdate, onCurate }: AdminInboxProps) {
  const tabs: [InboxFilter, string][] = [
    ["all", "全部"],
    ["new", `没处理 ${data?.counts.new ?? ""}`],
    ["done", `处理了 ${data?.counts.done ?? ""}`],
  ];
  return (
    <div className="max-w-4xl">
      <h1 className="text-2xl font-semibold">{title}</h1>
      <div className="mt-4 flex gap-1 text-sm" role="tablist">
        {tabs.map(([f, label]) => (
          <button
            key={f}
            type="button"
            role="tab"
            aria-selected={filter === f}
            onClick={() => onFilter(f)}
            className={cn(
              "rounded-md px-3 py-1.5 transition-colors",
              filter === f ? "bg-accent font-medium text-foreground" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {label.trim()}
          </button>
        ))}
      </div>
      {!data ? (
        <div className="mt-6 flex flex-col gap-4" aria-busy="true">
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={i} className="h-20 w-full" />
          ))}
        </div>
      ) : data.items.length === 0 ? (
        <p className="mt-10 text-[15px] text-body">{filter === "new" ? "都处理完了。" : "还没有。"}</p>
      ) : (
        <ul className="mt-2">
          {data.items.map((it) => (
            <Row key={it.id} kind={kind} item={it} onUpdate={onUpdate} onCurate={onCurate} />
          ))}
        </ul>
      )}
    </div>
  );
}
