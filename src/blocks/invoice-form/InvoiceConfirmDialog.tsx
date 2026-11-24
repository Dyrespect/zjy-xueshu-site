import { Loader2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import type { InvoiceFields, InvoicePublicConfig } from "@/lib/invoice-types";
import { FIELD_ORDER } from "@/lib/invoice-types";

export interface InvoiceConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  config: InvoicePublicConfig;
  fields: InvoiceFields;
  /** 金额（交付页有：实付多少开多少） */
  amountText?: string;
  confirmLabel?: string;
  busy?: boolean;
  error?: string;
  onConfirm: () => void;
}

/** 提交前核对一遍：抬头、税号开出后改不了，大字列出来，点「核对无误」才提交。只吃 props。 */
export function InvoiceConfirmDialog(props: InvoiceConfirmDialogProps) {
  const { open, onOpenChange, config, fields: f, amountText, confirmLabel = "核对无误，提交", busy, error, onConfirm } = props;
  const kind = config.kinds.find((k) => k.key === f.kind);
  const rows: [string, string][] = [["发票类型", kind?.label ?? f.kind]];
  for (const k of FIELD_ORDER) {
    const val = k === "tax_id" ? f.tax_id.replace(/[\s-]/g, "").toUpperCase() : f[k].trim();
    if (val) rows.push([k === "title" && f.title_kind === "personal" ? "抬头（姓名）" : (config.labels[k] ?? k), val]);
  }
  if (amountText) rows.push(["开票金额", amountText]);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>核对发票信息</DialogTitle>
          <DialogDescription>{config.notice}</DialogDescription>
        </DialogHeader>
        <dl className="flex flex-col divide-y rounded-lg border">
          {rows.map(([label, val]) => (
            <div key={label} className="flex flex-col gap-0.5 px-4 py-2.5 sm:flex-row sm:gap-4">
              <dt className="w-28 shrink-0 text-xs text-muted-foreground sm:pt-0.5">{label}</dt>
              <dd className={label === "纳税人识别号" ? "font-mono text-base tracking-wide break-all text-foreground" : "text-base break-all text-foreground"}>
                {val}
              </dd>
            </div>
          ))}
        </dl>
        <p className="text-xs leading-relaxed text-muted-foreground">
          销售方：{config.seller_name}；开票项目：{config.item_name}。开票金额就是你实付的钱，不另加税。
        </p>
        {error ? <p className="text-sm text-destructive">{error}</p> : null}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={busy}>
            回去改
          </Button>
          <Button onClick={onConfirm} disabled={busy}>
            {busy ? <Loader2 className="animate-spin" /> : null}
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
