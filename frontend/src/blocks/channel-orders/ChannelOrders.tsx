import { Check, Copy } from "lucide-react";
import { useState } from "react";

import { msgTime } from "@/lib/intake-types";
import type { InboxRow, SignalKind } from "@/lib/shop-types";
import { cn } from "@/lib/utils";

export interface ChannelOrdersProps {
  rows: InboxRow[];
  onSignal: (row: InboxRow, kind: SignalKind) => void;
  onPasted: (row: InboxRow) => void;
}

const SIGNALS: { kind: SignalKind; label: string; ask?: string }[] = [
  { kind: "completed", label: "平台已完成" },
  { kind: "refund_requested", label: "申请退款了", ask: "买家在平台上申请了退款？这一单先暂停（不开工、不交下一版、不发最终版）。" },
  { kind: "refund_closed", label: "退款申请关了" },
  { kind: "refund", label: "已退款", ask: "平台上已经退款了？订单作废、激活码作废，不能撤回。" },
];

const btn = "rounded-md border px-2.5 py-1 text-xs text-body hover:bg-accent";

/** 平台订单（人工录的、固定链接核对过的）：现在到哪一步、发货文案、平台那边有变化时点一下。只吃 props。 */
export function ChannelOrders({ rows, onSignal, onPasted }: ChannelOrdersProps) {
  const [copied, setCopied] = useState<number | null>(null);
  if (!rows.length) return <p className="rounded-lg border px-4 py-6 text-sm text-muted-foreground">还没有平台订单。</p>;
  return (
    <ul className="flex flex-col divide-y rounded-lg border">
      {rows.map((r) => {
        const closed = r.stage === "void" || r.stage === "delivered" || !r.order_id;
        return (
          <li key={r.id} className="flex flex-col gap-2 px-4 py-3">
            <div className="flex flex-wrap items-baseline gap-x-4 gap-y-1 text-sm">
              <span className="w-12 shrink-0 text-xs text-muted-foreground">{r.platform_label}</span>
              <span className="font-medium text-foreground tabular-nums">{r.platform_order_id}</span>
              <span className="text-body">{r.sku_name}</span>
              {r.code ? <span className="font-mono text-xs text-body">{r.code}</span> : null}
              <span className={cn("text-xs", r.exit === "manual" && !r.pasted_at ? "font-medium text-foreground" : "text-muted-foreground")}>
                {r.exit === "manual" && r.pasted_at ? "文案贴好了" : r.exit_label}
              </span>
              {r.stage_label ? (
                <span className="text-xs text-muted-foreground">
                  订单：{r.stage_label}
                  {r.hold ? "（暂停中）" : ""}
                  {r.completed_at
                    ? r.stage === "completed" || r.stage === "delivered"
                      ? ""
                      : " · 平台已完成（先记下了，交水印版时直接放最终版）"
                    : ""}
                </span>
              ) : null}
              <span className="ml-auto text-xs text-muted-foreground">{msgTime(r.created_at)}</span>
            </div>
            {r.error ? <p className="text-xs text-destructive">{r.error}</p> : null}
            <div className="flex flex-wrap items-center gap-2">
              {r.text ? (
                <button
                  type="button"
                  className={cn(btn, "inline-flex items-center gap-1")}
                  onClick={() => navigator.clipboard?.writeText(r.text).then(() => { setCopied(r.id); window.setTimeout(() => setCopied(null), 1500); })}
                >
                  {copied === r.id ? <Check className="size-3" /> : <Copy className="size-3" />}
                  {copied === r.id ? "复制好了" : "复制发货文案"}
                </button>
              ) : null}
              {r.exit === "manual" && !r.pasted_at ? (
                <button type="button" className={btn} onClick={() => onPasted(r)}>贴好了</button>
              ) : null}
              {!closed
                ? SIGNALS.map((s) => (
                    <button
                      key={s.kind}
                      type="button"
                      className={btn}
                      onClick={() => {
                        if (!s.ask || window.confirm(s.ask)) onSignal(r, s.kind);
                      }}
                    >
                      {s.label}
                    </button>
                  ))
                : null}
            </div>
          </li>
        );
      })}
    </ul>
  );
}
