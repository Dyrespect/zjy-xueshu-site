import { msgTime } from "@/lib/intake-types";
import type { DueItem } from "@/lib/shop-types";
import { cn } from "@/lib/utils";

export interface ChannelDueProps {
  items: DueItem[];
  /** 待核对的订单号：通过 / 不通过 */
  onVerify: (item: DueItem, ok: boolean) => void;
  /** 跳到对应的页签（平台订单、网页订单） */
  onOpen: (item: DueItem) => void;
}

const KIND_LABEL: Record<string, string> = {
  verify: "待核对",
  paste: "待贴文案",
  completion: "看一眼已完成",
  problem: "没发出码",
  price: "标价对不上",
  paid_no_code: "付了没发码",
  bad_notify: "支付通知",
  refund_stuck: "退款卡住",
};

/** 「该看一眼」：要你动手的事排在前面，每条一句话 + 要做什么。只吃 props。 */
export function ChannelDue({ items, onVerify, onOpen }: ChannelDueProps) {
  if (!items.length) {
    return <p className="rounded-lg border px-4 py-6 text-sm text-muted-foreground">都处理完了，没有要看的。</p>;
  }
  return (
    <ul className="flex flex-col divide-y rounded-lg border">
      {items.map((it, i) => (
        <li key={`${it.kind}-${it.inbox_id ?? it.order_id ?? i}-${i}`} className="flex flex-wrap items-start gap-x-4 gap-y-2 px-4 py-3">
          <span
            className={cn(
              "mt-0.5 w-24 shrink-0 text-xs",
              it.level === "high" ? "font-medium text-foreground" : "text-muted-foreground",
            )}
          >
            {KIND_LABEL[it.kind] ?? it.kind}
          </span>
          <div className="flex min-w-0 flex-1 flex-col gap-0.5">
            <span className="text-sm text-foreground">{it.title}</span>
            <span className="text-xs text-muted-foreground">
              {it.detail}
              {it.at ? ` · ${msgTime(it.at)}` : ""}
            </span>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {it.kind === "verify" ? (
              <>
                <button type="button" className="rounded-md bg-primary px-3 py-1 text-xs font-medium text-primary-foreground hover:bg-primary-hover" onClick={() => onVerify(it, true)}>
                  对上了，发码
                </button>
                <button type="button" className="rounded-md border px-3 py-1 text-xs text-body hover:bg-accent" onClick={() => onVerify(it, false)}>
                  对不上
                </button>
              </>
            ) : it.kind === "price" ? null : (
              <button type="button" className="rounded-md border px-3 py-1 text-xs text-body hover:bg-accent" onClick={() => onOpen(it)}>
                去看
              </button>
            )}
          </div>
        </li>
      ))}
    </ul>
  );
}
