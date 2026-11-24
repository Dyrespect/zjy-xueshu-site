import { Download, FileText, Loader2 } from "lucide-react";
import { useState } from "react";

import { InvoiceConfirmDialog, InvoiceFieldsForm } from "@/blocks/invoice-form";
import { Button } from "@/components/ui/button";
import { fileSize } from "@/lib/intake-types";
import {
  EMPTY_FIELDS,
  quickCheck,
  type FieldKey,
  type InvoiceFields,
  type InvoicePanelData,
  type InvoiceView,
} from "@/lib/invoice-types";
import { cn } from "@/lib/utils";

/** 提交被后端退回时带的字段（页面把 ApiError 转成这个抛出来） */
export class InvoiceFieldError extends Error {
  readonly field: string;

  constructor(message: string, field: string) {
    super(message);
    this.field = field;
  }
}

export interface InvoicePanelProps {
  data: InvoicePanelData;
  /** 提交申请，返回给客人看的一句话；字段不对抛 InvoiceFieldError */
  onApply: (fields: InvoiceFields) => Promise<string>;
  onWithdraw: (invoiceId: number) => Promise<string>;
  /** delivery：交付页（宽、上面有细线）；pay：付款结果页（窄、带边框） */
  variant?: "delivery" | "pay";
}

const KIND_LABEL: Record<string, string> = { pdf: "PDF", ofd: "OFD（版式文件）", xml: "XML（数据文件）" };

function Summary({ inv }: { inv: InvoiceView }) {
  const rows: [string, string][] = [
    ["发票类型", inv.kind_label],
    ["抬头", inv.title],
    ...(inv.tax_id ? ([["纳税人识别号", inv.tax_id]] as [string, string][]) : []),
    ["收票邮箱", inv.email],
    ...(inv.remark ? ([["备注", inv.remark]] as [string, string][]) : []),
    ...(inv.amount ? ([["开票金额", `${inv.amount} 元`]] as [string, string][]) : []),
  ];
  return (
    <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-[7rem_minmax(0,1fr)]">
      {rows.map(([k, v]) => (
        <div key={k} className="contents">
          <dt className="text-muted-foreground">{k}</dt>
          <dd className={cn("break-all text-foreground", k === "纳税人识别号" && "font-mono tracking-wide")}>{v}</dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * 交付页 / 付款结果页的「发票」一块：没申请的能申请（订单没完成先存着，完成后自动提交）；
 * 申请了的看进度、开出前能撤回；开好的下载；驳回、作废的看原因再申请。只吃 props。
 */
export function InvoicePanel({ data, onApply, onWithdraw, variant = "delivery" }: InvoicePanelProps) {
  const [formOpen, setFormOpen] = useState(false);
  const [fields, setFields] = useState<InvoiceFields>(() => {
    const last = data.history[0];
    return last ? { ...EMPTY_FIELDS, ...pick(last) } : EMPTY_FIELDS;
  });
  const [errors, setErrors] = useState<Partial<Record<FieldKey | "kind" | "title_kind", string>>>({});
  const [confirm, setConfirm] = useState(false);
  const [askWithdraw, setAskWithdraw] = useState(false);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [dialogError, setDialogError] = useState("");
  const cur = data.current;
  const cfg = data.config;
  if (!cur && !data.history.length && !data.can_apply && !data.why_not) return null;

  const required = cfg.kinds.find((k) => k.key === fields.kind)?.required ?? [];
  const last = !cur ? data.history.find((h) => ["rejected", "blocked", "voided"].includes(h.step)) : undefined;

  const submit = async () => {
    setBusy(true);
    setDialogError("");
    try {
      const note = await onApply(fields);
      setConfirm(false);
      setFormOpen(false);
      setMsg(note);
    } catch (e) {
      if (e instanceof InvoiceFieldError && e.field && e.field !== "confirmed") {
        setErrors({ [e.field]: e.message });
        setConfirm(false);
      } else {
        setDialogError(e instanceof Error ? e.message : "没提交成功，再试一次");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <section
      aria-label="发票"
      data-testid="invoice-panel"
      className={variant === "delivery" ? "mt-8 border-t pt-6" : "flex flex-col gap-4 rounded-lg border px-5 py-5"}
    >
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className={variant === "delivery" ? "text-lg font-semibold text-foreground" : "text-base font-semibold text-foreground"}>发票</h2>
        {cur ? <span className="text-sm text-body">{cur.stage_label}</span> : null}
      </div>

      {cur ? (
        <div className={cn("flex flex-col gap-4", variant === "delivery" && "mt-3")}>
          <p className="text-sm text-foreground">{cur.note}</p>
          {cur.step === "issued" && cur.files.length ? (
            <ul className="flex flex-col divide-y rounded-xl border">
              {cur.files.map((f) => (
                <li key={f.id} className="flex items-center gap-3 px-4 py-3">
                  <FileText className="size-5 shrink-0 text-muted-foreground" />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm text-foreground">{f.name}</div>
                    <div className="text-xs text-muted-foreground">
                      {KIND_LABEL[f.kind] ?? f.kind} · {fileSize(f.size)}
                    </div>
                  </div>
                  <Button asChild size="sm" variant={f.kind === "pdf" ? "default" : "outline"}>
                    <a href={f.url} download>
                      <Download />
                      下载
                    </a>
                  </Button>
                </li>
              ))}
            </ul>
          ) : null}
          <Summary inv={cur} />
          {cur.can_withdraw ? (
            askWithdraw ? (
              <div className="flex flex-wrap items-center gap-2 text-sm text-body">
                <span>撤回后可以改好重新提交。</span>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={busy}
                  onClick={async () => {
                    setBusy(true);
                    try {
                      setMsg(await onWithdraw(cur.id));
                      setFields({ ...EMPTY_FIELDS, ...pick(cur) });
                    } catch (e) {
                      setMsg(e instanceof Error ? e.message : "没撤回成功");
                    } finally {
                      setBusy(false);
                      setAskWithdraw(false);
                    }
                  }}
                >
                  {busy ? <Loader2 className="animate-spin" /> : null}
                  确定撤回
                </Button>
                <Button size="sm" variant="ghost" onClick={() => setAskWithdraw(false)}>
                  不撤了
                </Button>
              </div>
            ) : (
              <div>
                <Button size="sm" variant="outline" onClick={() => setAskWithdraw(true)}>
                  信息填错了，撤回重填
                </Button>
              </div>
            )
          ) : null}
        </div>
      ) : (
        <div className={cn("flex flex-col gap-4", variant === "delivery" && "mt-2")}>
          {last ? <p className="text-sm text-foreground">上一次{last.note}</p> : null}
          {data.can_apply ? (
            formOpen ? (
              <div className={cn("flex flex-col gap-4", variant === "delivery" && "rounded-lg border px-4 py-4 sm:max-w-2xl")}>
                <InvoiceFieldsForm
                  config={cfg}
                  value={fields}
                  onChange={(v) => {
                    setFields(v);
                    if (Object.keys(errors).length) setErrors({});
                  }}
                  errors={errors}
                  idPrefix={`inv-${variant}`}
                />
                <p className="text-xs leading-relaxed text-muted-foreground">{cfg.notice}</p>
                <div className="flex flex-wrap gap-2">
                  <Button
                    onClick={() => {
                      const errs = quickCheck(fields, required, cfg.labels);
                      setErrors(errs);
                      if (Object.keys(errs).length) return;
                      setDialogError("");
                      setConfirm(true);
                    }}
                  >
                    下一步：核对
                  </Button>
                  <Button variant="ghost" onClick={() => setFormOpen(false)}>
                    先不填
                  </Button>
                </div>
              </div>
            ) : (
              <div className="flex flex-col items-start gap-3">
                <p className="text-sm text-body">
                  {data.apply_note || "报销要发票的话在这里申请，开票金额就是实付金额。"}
                  {data.apply_note ? "，现在可以先填好。" : ""}
                </p>
                <Button variant="outline" onClick={() => setFormOpen(true)}>
                  {last ? "重新申请发票" : "申请发票"}
                </Button>
              </div>
            )
          ) : data.why_not ? (
            <p className="text-sm text-body">{data.why_not}</p>
          ) : null}
        </div>
      )}
      {msg ? (
        <p className="mt-3 text-sm text-foreground" aria-live="polite">
          {msg}
        </p>
      ) : null}
      {data.history.filter((h) => h !== last).length ? (
        <details className="mt-3 text-sm">
          <summary className="cursor-pointer text-muted-foreground">以前的申请</summary>
          <ul className="mt-2 flex flex-col gap-1 text-body">
            {data.history
              .filter((h) => h !== last)
              .map((h) => (
                <li key={h.id}>
                  {h.title} · {h.stage_label}
                  {h.reason ? `：${h.reason}` : ""}
                </li>
              ))}
          </ul>
        </details>
      ) : null}
      <InvoiceConfirmDialog
        open={confirm}
        onOpenChange={setConfirm}
        config={cfg}
        fields={fields}
        busy={busy}
        error={dialogError}
        onConfirm={submit}
      />
    </section>
  );
}

function pick(v: InvoiceView): Partial<InvoiceFields> {
  const { kind, title_kind, title, tax_id, email, bank_name, bank_account, address, phone, remark } = v;
  return { kind, title_kind, title, tax_id, email, bank_name, bank_account, address, phone, remark };
}
