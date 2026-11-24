import { Check, Copy, Download, Loader2 } from "lucide-react";
import { useState } from "react";

import { InvoiceFieldsForm } from "@/blocks/invoice-form";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { msgTime } from "@/lib/intake-types";
import type { AdminInvoiceRow, InvoiceFields, InvoicePublicConfig } from "@/lib/invoice-types";
import { cn } from "@/lib/utils";

export interface AdminInvoicesProps {
  rows: AdminInvoiceRow[];
  config: InvoicePublicConfig;
  /** 每个动作返回给负责人看的一句话（成功）；失败抛错（错误信息三件） */
  onIssue: (row: AdminInvoiceRow, body: { files: File[]; amount: string; invoice_no: string; note: string }) => Promise<string>;
  onReject: (row: AdminInvoiceRow, reason: string) => Promise<string>;
  onVoid: (row: AdminInvoiceRow, reason: string, reopen: boolean, fields?: InvoiceFields) => Promise<string>;
  onEdit: (row: AdminInvoiceRow, fields: InvoiceFields) => Promise<string>;
  onCopy?: (text: string) => Promise<void>;
  empty?: string;
}

type Action = { kind: "issue" | "reject" | "void" | "edit"; row: AdminInvoiceRow } | null;

const inputCls = "h-9 w-full rounded-md border border-input bg-background px-2.5 text-sm text-foreground outline-none focus-visible:border-ring";
const areaCls = "field-sizing-content min-h-20 w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground outline-none focus-visible:border-ring";

function fieldsOf(r: AdminInvoiceRow): InvoiceFields {
  const { kind, title_kind, title, tax_id, email, bank_name, bank_account, address, phone, remark } = r;
  return { kind, title_kind, title, tax_id, email, bank_name, bank_account, address, phone, remark };
}

function CopyButton({ text, onCopy }: { text: string; onCopy?: (t: string) => Promise<void> }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      className="inline-flex items-center gap-1 rounded-md border px-2 py-1 text-xs text-body hover:bg-accent"
      onClick={() => {
        const p = onCopy ? onCopy(text) : (navigator.clipboard?.writeText(text) ?? Promise.resolve());
        p.then(() => {
          setDone(true);
          window.setTimeout(() => setDone(false), 1600);
        }).catch(() => undefined);
      }}
    >
      {done ? <Check className="size-3" /> : <Copy className="size-3" />}
      {done ? "复制好了" : "复制抬头信息"}
    </button>
  );
}

/** 后台发票列表：待开票、等订单完成、已开票、驳回作废撤回。复制抬头、上传开好的发票、驳回、作废重开、开出前改信息。只吃 props。 */
export function AdminInvoices({ rows, config, onIssue, onReject, onVoid, onEdit, onCopy, empty = "这里没有" }: AdminInvoicesProps) {
  const [act, setAct] = useState<Action>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [amount, setAmount] = useState("");
  const [invoiceNo, setInvoiceNo] = useState("");
  const [note, setNote] = useState("");
  const [reason, setReason] = useState("");
  const [reopen, setReopen] = useState(true);
  const [fields, setFields] = useState<InvoiceFields | null>(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  const open = (kind: NonNullable<Action>["kind"], row: AdminInvoiceRow) => {
    setAct({ kind, row });
    setFiles([]);
    setAmount(row.max_amount);
    setInvoiceNo("");
    setNote("");
    setReason("");
    setReopen(true);
    setFields(fieldsOf(row));
    setMsg("");
  };
  const run = async (fn: () => Promise<string>) => {
    setBusy(true);
    setMsg("");
    try {
      await fn();
      setAct(null);
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "没成");
    } finally {
      setBusy(false);
    }
  };

  if (!rows.length) return <p className="rounded-lg border px-4 py-6 text-sm text-muted-foreground">{empty}</p>;
  const title = { issue: "上传开好的发票", reject: "驳回申请", void: "作废发票", edit: "改发票信息" };
  return (
    <>
      <div className="overflow-x-auto rounded-lg border">
        <table className="w-full min-w-[920px] text-sm">
          <thead>
            <tr className="border-b text-left text-xs text-muted-foreground">
              <th className="px-4 py-2 font-normal">单号</th>
              <th className="px-4 py-2 font-normal">金额（元）</th>
              <th className="px-4 py-2 font-normal">抬头</th>
              <th className="px-4 py-2 font-normal">纳税人识别号</th>
              <th className="px-4 py-2 font-normal">类型</th>
              <th className="px-4 py-2 font-normal">申请时间</th>
              <th className="px-4 py-2 font-normal">状态</th>
              <th className="px-4 py-2" />
            </tr>
          </thead>
          <tbody className="divide-y">
            {rows.map((r) => (
              <tr key={r.id} className="align-top" data-testid={`invoice-row-${r.id}`}>
                <td className="px-4 py-3 whitespace-nowrap">
                  <span className="text-foreground tabular-nums">{r.order_no || "—"}</span>
                  <span className="block text-xs text-muted-foreground">
                    {r.platform_name} · {r.source_label}
                  </span>
                </td>
                <td className="px-4 py-3 whitespace-nowrap tabular-nums">
                  <span className="text-foreground">{r.amount || r.max_amount || "—"}</span>
                  {r.refunded && r.refunded !== "0.00" ? (
                    <span className="block text-xs text-muted-foreground">
                      实付 {r.paid}，退了 {r.refunded}
                    </span>
                  ) : r.amount ? (
                    <span className="block text-xs text-muted-foreground">已开</span>
                  ) : null}
                </td>
                <td className="max-w-[16rem] px-4 py-3 text-foreground">
                  {r.title}
                  <span className="block text-xs break-all text-muted-foreground">{r.email}</span>
                  {r.warnings.map((w) => (
                    <span key={w} className="mt-1 block text-xs font-medium text-foreground">
                      注意：{w}
                    </span>
                  ))}
                </td>
                <td className="px-4 py-3 font-mono text-xs break-all text-body">{r.tax_id || "—"}</td>
                <td className="px-4 py-3 text-xs whitespace-nowrap text-body">{r.kind_label}</td>
                <td className="px-4 py-3 text-xs whitespace-nowrap text-muted-foreground">{msgTime(r.requested_at ?? r.created_at)}</td>
                <td className="px-4 py-3 text-xs text-foreground">
                  {r.stage_label}
                  {r.reason ? <span className="block max-w-[12rem] text-muted-foreground">{r.reason}</span> : null}
                  {r.files.map((f) => (
                    <a key={f.id} href={f.url} target="_blank" rel="noreferrer" className="mt-1 flex items-center gap-1 text-primary hover:underline">
                      <Download className="size-3" />
                      {f.kind.toUpperCase()}
                    </a>
                  ))}
                </td>
                <td className="px-4 py-3">
                  <div className="flex flex-col items-end gap-1.5">
                    <CopyButton text={r.copy_text} onCopy={onCopy} />
                    {r.step === "pending" ? (
                      <Button size="xs" onClick={() => open("issue", r)}>
                        开好了，上传
                      </Button>
                    ) : null}
                    {r.step === "pending" || r.step === "waiting" ? (
                      <div className="flex gap-1.5">
                        <button type="button" className="rounded-md border px-2 py-1 text-xs text-body hover:bg-accent" onClick={() => open("edit", r)}>
                          改信息
                        </button>
                        <button type="button" className="rounded-md border px-2 py-1 text-xs text-body hover:bg-accent" onClick={() => open("reject", r)}>
                          驳回
                        </button>
                      </div>
                    ) : null}
                    {r.step === "issued" ? (
                      <button type="button" className="rounded-md border px-2 py-1 text-xs text-body hover:bg-accent" onClick={() => open("void", r)}>
                        作废 / 重开
                      </button>
                    ) : null}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <Dialog open={!!act} onOpenChange={(v) => !v && setAct(null)}>
        <DialogContent className="max-h-[90vh] overflow-y-auto sm:max-w-xl">
          {act ? (
            <>
              <DialogHeader>
                <DialogTitle>{title[act.kind]}</DialogTitle>
                <DialogDescription>
                  单号 {act.row.order_no}，{act.row.title}。
                  {act.kind === "issue" ? `最多能开 ${act.row.max_amount || "（查不到实付，手填）"} 元（实付减已退，含税不另加税）。` : null}
                  {act.kind === "reject" ? "原因客人会看到，照着改了能重新申请。" : null}
                  {act.kind === "void" ? "红冲、作废本身在开票软件里做；这里让系统和客人知道。原因客人会看到。" : null}
                  {act.kind === "edit" ? "客人在聊天里说填错了，开出前在这里改；改动留记录。" : null}
                </DialogDescription>
              </DialogHeader>
              {act.kind === "issue" ? (
                <div className="flex flex-col gap-3">
                  <pre className="rounded-md border bg-card px-3 py-2 text-xs leading-relaxed whitespace-pre-wrap text-body">{act.row.copy_text}</pre>
                  <label className="flex flex-col gap-1">
                    <span className="text-xs text-muted-foreground">发票文件（PDF，最好连 OFD、XML 一起；最多 5 个）</span>
                    <input
                      aria-label="发票文件"
                      type="file"
                      multiple
                      accept=".pdf,.ofd,.xml,application/pdf,application/xml,text/xml"
                      className="text-sm text-body file:mr-3 file:rounded-md file:border file:bg-background file:px-3 file:py-1.5 file:text-sm file:text-foreground"
                      onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
                    />
                  </label>
                  <div className="grid gap-3 sm:grid-cols-2">
                    <label className="flex flex-col gap-1">
                      <span className="text-xs text-muted-foreground">开票金额（元）</span>
                      <input aria-label="开票金额" className={inputCls} value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" />
                    </label>
                    <label className="flex flex-col gap-1">
                      <span className="text-xs text-muted-foreground">发票号码（选填）</span>
                      <input aria-label="发票号码" className={inputCls} value={invoiceNo} onChange={(e) => setInvoiceNo(e.target.value)} />
                    </label>
                  </div>
                  <label className="flex flex-col gap-1">
                    <span className="text-xs text-muted-foreground">备注（自己看的）</span>
                    <input aria-label="出票备注" className={inputCls} value={note} onChange={(e) => setNote(e.target.value)} />
                  </label>
                </div>
              ) : null}
              {act.kind === "reject" || act.kind === "void" ? (
                <label className="flex flex-col gap-1">
                  <span className="text-xs text-muted-foreground">原因（客人会看到）</span>
                  <textarea aria-label="原因" className={areaCls} value={reason} onChange={(e) => setReason(e.target.value)} />
                </label>
              ) : null}
              {act.kind === "void" ? (
                <label className="flex items-center gap-2 text-sm text-foreground">
                  <input type="checkbox" checked={reopen} onChange={(e) => setReopen(e.target.checked)} />
                  作废后重开一张（照下面的信息，进待开票）
                </label>
              ) : null}
              {(act.kind === "edit" || (act.kind === "void" && reopen)) && fields ? (
                <div className="rounded-lg border px-4 py-4">
                  <InvoiceFieldsForm config={config} value={fields} onChange={setFields} idPrefix="admin-inv" />
                </div>
              ) : null}
              {msg ? <p className="text-sm whitespace-pre-wrap text-destructive">{msg}</p> : null}
              <DialogFooter>
                <Button variant="outline" onClick={() => setAct(null)} disabled={busy}>
                  取消
                </Button>
                <Button
                  variant={act.kind === "void" || act.kind === "reject" ? "destructive" : "default"}
                  disabled={busy || ((act.kind === "reject" || act.kind === "void") && reason.trim().length < 2) || (act.kind === "issue" && !files.length)}
                  className={cn(busy && "opacity-80")}
                  onClick={() =>
                    run(() => {
                      const row = act.row;
                      if (act.kind === "issue") return onIssue(row, { files, amount, invoice_no: invoiceNo, note });
                      if (act.kind === "reject") return onReject(row, reason.trim());
                      if (act.kind === "void") return onVoid(row, reason.trim(), reopen, reopen && fields ? fields : undefined);
                      return onEdit(row, fields ?? fieldsOf(row));
                    })
                  }
                >
                  {busy ? <Loader2 className="animate-spin" /> : null}
                  {{ issue: "标记已开", reject: "驳回", void: reopen ? "作废并重开" : "作废", edit: "保存" }[act.kind]}
                </Button>
              </DialogFooter>
            </>
          ) : null}
        </DialogContent>
      </Dialog>
    </>
  );
}
