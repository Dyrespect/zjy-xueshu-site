import { Loader2 } from "lucide-react";
import { useState } from "react";

import { InvoiceFieldsForm } from "@/blocks/invoice-form";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { EMPTY_FIELDS, type InvoiceFields, type InvoicePublicConfig, type OrderLookup } from "@/lib/invoice-types";

export interface ManualInvoiceDialogProps {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  config: InvoicePublicConfig;
  onLookup: (orderId: number) => Promise<OrderLookup>;
  onSubmit: (orderId: number, fields: InvoiceFields) => Promise<string>;
}

const inputCls = "h-9 w-32 rounded-md border border-input bg-background px-2.5 text-sm text-foreground outline-none focus-visible:border-ring";

/** 给任一渠道的单录一条发票记录（平台单客人不能自己申请）：先查单（渠道、实付、完成没），再填抬头。只吃 props。 */
export function ManualInvoiceDialog({ open, onOpenChange, config, onLookup, onSubmit }: ManualInvoiceDialogProps) {
  const [no, setNo] = useState("");
  const [look, setLook] = useState<OrderLookup | null>(null);
  const [fields, setFields] = useState<InvoiceFields>(EMPTY_FIELDS);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const reset = (v: boolean) => {
    if (!v) {
      setNo("");
      setLook(null);
      setFields(EMPTY_FIELDS);
      setMsg("");
    }
    onOpenChange(v);
  };
  return (
    <Dialog open={open} onOpenChange={reset}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
        <DialogHeader>
          <DialogTitle>给一单录发票</DialogTitle>
          <DialogDescription>平台单（小红书、闲鱼、抖音）客人不能在网上申请，客人找你要时在这里录；也要订单已完成、没退款。</DialogDescription>
        </DialogHeader>
        <div className="flex items-end gap-2">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">单号</span>
            <input aria-label="单号" className={inputCls} value={no} onChange={(e) => setNo(e.target.value.replace(/\D/g, ""))} inputMode="numeric" />
          </label>
          <Button
            variant="outline"
            disabled={!no || busy}
            onClick={async () => {
              setMsg("");
              try {
                setLook(await onLookup(Number(no)));
              } catch (e) {
                setLook(null);
                setMsg(e instanceof Error ? e.message : "查不到");
              }
            }}
          >
            查这一单
          </Button>
        </div>
        {look ? (
          <div className="rounded-md border bg-card px-3 py-2 text-sm text-body">
            单号 {look.order_no} · {look.platform_name} · {look.stage_label} · 实付 {look.paid || "查不到"}
            {look.refunded && look.refunded !== "0.00" ? `（退了 ${look.refunded}）` : ""}
            {look.gate !== "open" ? <span className="mt-1 block font-medium text-foreground">现在不能开：{look.reason}</span> : null}
            {look.active_invoice_id ? <span className="mt-1 block font-medium text-foreground">这单已经有一张在办的发票了</span> : null}
            {look.warnings.map((w) => (
              <span key={w} className="mt-1 block text-xs">
                注意：{w}
              </span>
            ))}
          </div>
        ) : null}
        {look ? <InvoiceFieldsForm config={config} value={fields} onChange={setFields} idPrefix="manual-inv" /> : null}
        {msg ? <p className="text-sm whitespace-pre-wrap text-destructive">{msg}</p> : null}
        <DialogFooter>
          <Button variant="outline" onClick={() => reset(false)} disabled={busy}>
            取消
          </Button>
          <Button
            disabled={!look || busy || look.gate === "blocked" || !!look.active_invoice_id}
            onClick={async () => {
              if (!look) return;
              setBusy(true);
              setMsg("");
              try {
                await onSubmit(look.order_id, fields);
                reset(false);
              } catch (e) {
                setMsg(e instanceof Error ? e.message : "没录上");
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? <Loader2 className="animate-spin" /> : null}
            录进去
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
