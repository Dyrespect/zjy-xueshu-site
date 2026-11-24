import { Loader2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import type { ReceiptState, RevisionState } from "@/lib/delivery-types";
import { cn } from "@/lib/utils";

export interface ReceiptPanelProps {
  receipt: ReceiptState;
  revision: RevisionState;
  /** 标了几处要改（写了内容的） */
  marked: number;
  busy: "confirm" | "claim" | null;
  notice?: string;
  onReview: () => void;
  onConfirm: () => void;
  onPlatformClaim: () => void;
  /** 陈列页里不贴底 */
  inline?: boolean;
}

/** 底部常驻一条：标了几处要改 · 提交修改意见；确认收货（自有渠道）或「去平台点确认收货」（平台单）。不挡内容：页面底部留了同样高的空。 */
export function ReceiptPanel({ receipt, revision, marked, busy, notice, onReview, onConfirm, onPlatformClaim, inline }: ReceiptPanelProps) {
  const [ask, setAsk] = useState(false);
  if (receipt.mode === "none" && !(revision.can_submit && marked) && !notice) return null;
  let line = notice || "";
  if (!line) {
    if (marked) line = `已标 ${marked} 处要改，都写好了就提交（${revision.after_delivery ? "用掉 1 轮" : "这一轮就用掉了"}）。`;
    else if (revision.open) line = "修改意见收到了，改好的一版还在这一页看。";
    else if (receipt.mode === "button") line = receipt.auto_confirm_text || receipt.hint;
    else if (receipt.mode === "platform") line = receipt.hint;
    else line = revision.hint;
  }
  return (
    <div className={cn("border-t bg-background", inline ? "rounded-lg border" : "fixed inset-x-0 bottom-0 z-40")} data-testid="receipt-panel">
      <div className="mx-auto flex max-w-5xl flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:gap-4">
        <p className="min-w-0 flex-1 text-sm leading-snug text-body">{line}</p>
        <div className="flex shrink-0 gap-2">
          {revision.can_submit && marked ? (
            <Button onClick={onReview} className="flex-1 sm:flex-none">
              提交修改意见（{marked}）
            </Button>
          ) : null}
          {receipt.mode === "button" ? (
            <Button variant={marked ? "outline" : "default"} onClick={() => setAsk(true)} disabled={busy === "confirm"} className="flex-1 sm:flex-none">
              {busy === "confirm" ? <Loader2 className="animate-spin" /> : null}
              确认收货
            </Button>
          ) : receipt.mode === "platform" ? (
            <Button variant="outline" onClick={onPlatformClaim} disabled={busy === "claim"} className="flex-1 sm:flex-none">
              我已经在{receipt.platform_name}点了
            </Button>
          ) : null}
        </div>
      </div>

      <Dialog open={ask} onOpenChange={setAsk}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>确认收货</DialogTitle>
            <DialogDescription className="text-body">
              确认后马上在这一页放出可编辑的 PPT 和讲稿，之后不支持退款；没用的修改次数照样能用。
            </DialogDescription>
          </DialogHeader>
          {marked ? <p className="text-sm text-foreground">你还标了 {marked} 处要改没提交：确认收货不会把它们交给我们，想改先提交修改意见。</p> : null}
          <DialogFooter>
            <Button variant="outline" onClick={() => setAsk(false)}>
              再看看
            </Button>
            <Button
              onClick={() => {
                setAsk(false);
                onConfirm();
              }}
            >
              确认收货
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
