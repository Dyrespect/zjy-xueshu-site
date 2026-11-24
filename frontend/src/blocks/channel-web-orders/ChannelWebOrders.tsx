import { Loader2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { msgTime } from "@/lib/intake-types";
import type { WebOrderRow } from "@/lib/shop-types";

export interface ChannelWebOrdersProps {
  rows: WebOrderRow[];
  /** 退款：金额是分；返回给人看的结果 */
  onRefund: (row: WebOrderRow, body: { amount_fen: number; scope: string; reason: string }) => Promise<string>;
}

const inputCls = "h-9 rounded-md border border-input bg-background px-2.5 text-sm text-foreground outline-none focus-visible:border-ring";

function yuan(fen: number): string {
  return `${Math.floor(fen / 100)}.${String(fen % 100).padStart(2, "0")}`;
}

function toFen(s: string): number {
  const [w, f = ""] = s.trim().split(".");
  return Number(w || 0) * 100 + Number((f + "00").slice(0, 2));
}

/** 自有网页的单（待付款、已付、已退）。退款只在这里点：先退钱，退全款后订单和激活码作废。只吃 props。 */
export function ChannelWebOrders({ rows, onRefund }: ChannelWebOrdersProps) {
  const [target, setTarget] = useState<WebOrderRow | null>(null);
  const [amount, setAmount] = useState("");
  const [scope, setScope] = useState("full");
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const open = (r: WebOrderRow) => {
    setTarget(r);
    setAmount(yuan(r.paid_fen - r.refunded_fen));
    setScope("full");
    setReason("");
    setMsg("");
  };

  if (!rows.length) return <p className="rounded-lg border px-4 py-6 text-sm text-muted-foreground">还没有网页订单。</p>;
  return (
    <>
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full min-w-[720px] text-sm">
          <thead>
            <tr className="border-b text-left text-xs text-muted-foreground">
              <th className="px-4 py-2 font-normal">下单时间</th>
              <th className="px-4 py-2 font-normal">买了什么</th>
              <th className="px-4 py-2 font-normal">金额</th>
              <th className="px-4 py-2 font-normal">付款</th>
              <th className="px-4 py-2 font-normal">状态</th>
              <th className="px-4 py-2 font-normal">单 / 码</th>
              <th className="px-4 py-2" />
            </tr>
          </thead>
          <tbody className="divide-y">
            {rows.map((r) => (
              <tr key={r.id} className="align-top">
                <td className="px-4 py-2.5 text-xs whitespace-nowrap text-muted-foreground">{msgTime(r.created_at)}</td>
                <td className="px-4 py-2.5 text-body">
                  {r.sku_name}
                  {r.addons.length ? <span className="text-muted-foreground"> + {r.addons.join("、")}</span> : null}
                </td>
                <td className="px-4 py-2.5 text-foreground tabular-nums">
                  {r.amount}
                  {r.refunded_fen ? <span className="block text-xs text-muted-foreground">退了 {yuan(r.refunded_fen)}</span> : null}
                </td>
                <td className="px-4 py-2.5 text-xs text-muted-foreground">{r.method}{r.pay_node === "pay.fake" ? "（假网关）" : ""}</td>
                <td className="px-4 py-2.5 text-xs text-foreground">
                  {r.status_label}
                  {r.create_exit === "blocked" ? <span className="block text-destructive">没发码：买家退款太多次</span> : null}
                  {r.refunds.map((f) => (
                    <span key={f.id} className="block text-muted-foreground">
                      退 {f.amount}：{f.status_label}{f.void_result ? `，${f.void_result}` : ""}
                    </span>
                  ))}
                </td>
                <td className="px-4 py-2.5 text-xs text-body">
                  {r.order_id ? `#${r.order_id}` : "—"}
                  {r.code ? <span className="block font-mono">{r.code}</span> : null}
                </td>
                <td className="px-4 py-2.5 text-right">
                  {(r.status === "paid" || r.status === "part_refunded") && r.paid_fen > r.refunded_fen ? (
                    <button type="button" className="rounded-md border px-2.5 py-1 text-xs text-body hover:bg-accent" onClick={() => open(r)}>
                      退款
                    </button>
                  ) : null}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Dialog open={!!target} onOpenChange={(v) => !v && setTarget(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>退款</DialogTitle>
            <DialogDescription>
              {target ? `${target.sku_name}，实付 ${yuan(target.paid_fen)} 元，已退 ${yuan(target.refunded_fen)} 元。` : ""}
              钱原路退回；退全款后这一单作废、激活码作废，不能撤回。
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-3">
            <label className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">退多少（元）</span>
              <input aria-label="退多少" className={inputCls} value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" />
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">退的是什么</span>
              <select aria-label="退的是什么" className={inputCls} value={scope} onChange={(e) => setScope(e.target.value)}>
                <option value="full">整单</option>
                <option value="addon:rush">加急费（没在加急时限内交）</option>
                <option value="addon:revision">没用上的加购轮次</option>
                <option value="other">其他</option>
              </select>
            </label>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">原因（自己看的）</span>
              <input aria-label="原因" className={inputCls} value={reason} onChange={(e) => setReason(e.target.value)} />
            </label>
            {msg ? <p className="text-sm text-foreground">{msg}</p> : null}
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setTarget(null)}>取消</Button>
            <Button
              variant="destructive"
              disabled={busy || !target || toFen(amount) <= 0}
              onClick={async () => {
                if (!target) return;
                setBusy(true);
                try {
                  setMsg(await onRefund(target, { amount_fen: toFen(amount), scope, reason }));
                } catch (e) {
                  setMsg(e instanceof Error ? e.message : "没退成");
                } finally {
                  setBusy(false);
                }
              }}
            >
              {busy ? <Loader2 className="animate-spin" /> : null}
              确认退款
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
