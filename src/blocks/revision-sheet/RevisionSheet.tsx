import { Loader2, Paperclip } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import type { RevisionDraft } from "@/lib/delivery-types";

export interface RevisionSheetProps {
  open: boolean;
  drafts: RevisionDraft[];
  revisionsLeft: number;
  afterDelivery: boolean;
  busy: boolean;
  error?: string;
  onOpenChange: (open: boolean) => void;
  onSubmit: () => void;
}

/** 提交前把各页意见列一遍：含一轮修改，提交后就用掉了，请一次写全。 */
export function RevisionSheet({ open, drafts, revisionsLeft, afterDelivery, busy, error, onOpenChange, onSubmit }: RevisionSheetProps) {
  const rows = drafts.filter((d) => d.text.trim()).sort((a, b) => (a.page ?? 9999) - (b.page ?? 9999));
  const empty = drafts.length - rows.length;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85dvh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>提交修改意见</DialogTitle>
          <DialogDescription className="text-body">
            {afterDelivery
              ? `还剩 ${revisionsLeft} 轮修改，这次提交后用掉 1 轮；改好了直接放新的可编辑版。`
              : `含 ${revisionsLeft} 轮修改，这次提交后就用掉了。请看一遍，要改的地方都写全了再提交。`}
          </DialogDescription>
        </DialogHeader>
        <ol className="flex flex-col divide-y rounded-lg border">
          {rows.map((d) => (
            <li key={d.key} className="flex gap-3 px-4 py-3">
              <span className="w-14 shrink-0 text-sm font-medium text-foreground tabular-nums">{d.page ? `第 ${d.page} 页` : "整体"}</span>
              <div className="min-w-0 flex-1">
                <p className="text-sm leading-relaxed break-words whitespace-pre-wrap text-body">{d.text.trim()}</p>
                {d.files.length ? (
                  <p className="mt-1 flex items-center gap-1 text-xs text-muted-foreground">
                    <Paperclip className="size-3" />
                    {d.files.map((f) => f.name).join("、")}
                  </p>
                ) : null}
              </div>
            </li>
          ))}
        </ol>
        {empty ? <p className="text-sm text-muted-foreground">还有 {empty} 处标了「要改」但没写内容，不会提交。</p> : null}
        {error ? <p className="text-sm text-destructive">{error}</p> : null}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            再看看
          </Button>
          <Button onClick={onSubmit} disabled={busy || !rows.length}>
            {busy ? <Loader2 className="animate-spin" /> : null}
            确认提交（{rows.length} 条）
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
