import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { msgTime } from "@/lib/intake-types";
import type { InvoiceNoticeRow } from "@/lib/invoice-types";

export interface InvoiceNoticesProps {
  rows: InvoiceNoticeRow[];
  onSent: (row: InvoiceNoticeRow) => Promise<void>;
}

/** 待发的通知：还没有发邮件的服务，复制收件人和内容自己发，发了点一下。只吃 props。 */
export function InvoiceNotices({ rows, onSent }: InvoiceNoticesProps) {
  const [copied, setCopied] = useState<number | null>(null);
  if (!rows.length) return <p className="rounded-lg border px-4 py-6 text-sm text-muted-foreground">没有待发的通知。</p>;
  return (
    <ul className="flex flex-col divide-y rounded-lg border">
      {rows.map((n) => (
        <li key={n.id} className="flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-start sm:gap-4">
          <div className="min-w-0 flex-1">
            <div className="text-sm text-foreground">
              {n.target} <span className="text-xs text-muted-foreground">· 单号 {n.order_no} · {msgTime(n.created_at)}</span>
            </div>
            <div className="mt-0.5 text-sm font-medium text-foreground">{n.subject}</div>
            <p className="mt-0.5 text-sm break-all text-body">{n.text}</p>
          </div>
          <div className="flex shrink-0 gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() =>
                navigator.clipboard?.writeText(`${n.target}\n${n.subject}\n\n${n.text}`).then(() => {
                  setCopied(n.id);
                  window.setTimeout(() => setCopied(null), 1600);
                })
              }
            >
              {copied === n.id ? <Check /> : <Copy />}
              {copied === n.id ? "复制好了" : "复制"}
            </Button>
            <Button size="sm" onClick={() => onSent(n)}>
              发了
            </Button>
          </div>
        </li>
      ))}
    </ul>
  );
}
