import { Loader2 } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import type { FieldKey, InvoiceConfigFull, InvoiceSettingsData } from "@/lib/invoice-types";
import { cn } from "@/lib/utils";

export interface InvoiceSettingsFormProps {
  data: InvoiceSettingsData;
  onSave: (config: InvoiceConfigFull) => Promise<void>;
}

const textCls = "h-9 w-full max-w-md rounded-md border border-input bg-background px-2.5 text-sm text-foreground outline-none focus-visible:border-ring";
const numCls = "h-9 w-24 rounded-md border border-input bg-background px-2.5 text-sm text-foreground outline-none focus-visible:border-ring";
const areaCls = "field-sizing-content min-h-16 w-full max-w-2xl rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground outline-none focus-visible:border-ring";
const SPECIAL_FIELDS: { key: FieldKey; label: string }[] = [
  { key: "title", label: "抬头" },
  { key: "tax_id", label: "税号" },
  { key: "email", label: "邮箱" },
  { key: "bank_name", label: "开户行" },
  { key: "bank_account", label: "账号" },
  { key: "address", label: "地址" },
  { key: "phone", label: "电话" },
];

function Row({ label, children, finance, confirmed, onConfirm, note }: {
  label: string;
  children: ReactNode;
  finance?: string;
  confirmed?: boolean;
  onConfirm?: (v: boolean) => void;
  note?: string;
}) {
  return (
    <div className="grid gap-2 border-t py-4 first:border-t-0 sm:grid-cols-[12rem_minmax(0,1fr)] sm:gap-6">
      <div className="flex flex-col gap-1">
        <span className="text-sm font-medium text-foreground">{label}</span>
        {finance ? <span className="text-xs text-muted-foreground">{finance}</span> : null}
        {finance ? (
          <span className={cn("w-fit rounded-full border px-2 py-0.5 text-xs", confirmed ? "text-body" : "border-foreground font-medium text-foreground")}>
            {confirmed ? "财务已确认" : "待财务确认"}
          </span>
        ) : null}
      </div>
      <div className="flex flex-col gap-2">
        {children}
        {note ? <span className="text-xs text-muted-foreground">{note}</span> : null}
        {finance && onConfirm ? (
          <label className="flex items-center gap-2 text-xs text-body">
            <input type="checkbox" checked={!!confirmed} onChange={(e) => onConfirm(e.target.checked)} />
            财务已确认
          </label>
        ) : null}
      </div>
    </div>
  );
}

/** 发票设置：税率、纳税人类型、开票项目、专票开关这几项标「待财务确认」，财务确认一项勾一项。只吃 props。 */
export function InvoiceSettingsForm({ data, onSave }: InvoiceSettingsFormProps) {
  const [c, setC] = useState<InvoiceConfigFull>(data.config);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const set = (patch: Partial<InvoiceConfigFull>) => setC({ ...c, ...patch });
  const fin = (key: string) => ({
    finance: data.finance_fields[key],
    confirmed: c.confirmed_fields.includes(key),
    onConfirm: (v: boolean) =>
      set({ confirmed_fields: v ? [...c.confirmed_fields, key] : c.confirmed_fields.filter((x) => x !== key) }),
  });
  const toggle = <T extends string>(list: T[], item: T, on: boolean): T[] => (on ? [...new Set([...list, item])] : list.filter((x) => x !== item));
  const pendingCount = Object.keys(data.finance_fields).filter((k) => !c.confirmed_fields.includes(k)).length;

  return (
    <div className="flex max-w-4xl flex-col">
      {pendingCount ? (
        <p className="mb-4 rounded-md border px-4 py-3 text-sm text-foreground">
          还有 {pendingCount} 项待财务确认。默认值按 Edison 11-18 的话填（小规模纳税人、技术服务费、专票先关），税率留空等财务填。
        </p>
      ) : null}
      <Row label="网上受理发票申请" note="关掉后下单页、交付页都不出发票入口；后台照样能录。">
        <label className="flex items-center gap-2 text-sm text-foreground">
          <input type="checkbox" checked={c.enabled} onChange={(e) => set({ enabled: e.target.checked })} />
          受理
        </label>
      </Row>
      <Row label="销售方" note="营业执照上的名称和统一社会信用代码。">
        <input aria-label="销售方名称" className={textCls} value={c.seller_name} onChange={(e) => set({ seller_name: e.target.value })} />
        <input aria-label="销售方税号" className={cn(textCls, "font-mono")} value={c.seller_tax_id} onChange={(e) => set({ seller_tax_id: e.target.value })} />
      </Row>
      <Row label="纳税人类型" {...fin("taxpayer_type")}>
        <select aria-label="纳税人类型" className={textCls} value={c.taxpayer_type} onChange={(e) => set({ taxpayer_type: e.target.value as InvoiceConfigFull["taxpayer_type"] })}>
          <option value="小规模纳税人">小规模纳税人</option>
          <option value="一般纳税人">一般纳税人</option>
          <option value="">还不知道</option>
        </select>
      </Row>
      <Row label="税率" {...fin("tax_rate")} note="只显示在复制给财务的信息和导出表里；客人付多少开多少，不另加税。">
        <input aria-label="税率" className={numCls} value={c.tax_rate} placeholder="待财务填" onChange={(e) => set({ tax_rate: e.target.value })} />
      </Row>
      <Row label="开票项目名称" {...fin("item_name")}>
        <input aria-label="开票项目名称" className={textCls} value={c.item_name} onChange={(e) => set({ item_name: e.target.value })} />
      </Row>
      <Row label="专用发票" {...fin("special_enabled")} note="开了以后客人能选专票，要多填下面勾的几项。">
        <label className="flex items-center gap-2 text-sm text-foreground">
          <input type="checkbox" checked={c.special_enabled} onChange={(e) => set({ special_enabled: e.target.checked })} />
          开放专票
        </label>
        <div className="flex flex-wrap gap-3 text-sm text-body">
          {SPECIAL_FIELDS.map((f) => (
            <label key={f.key} className="flex items-center gap-1.5">
              <input
                type="checkbox"
                checked={c.required_special.includes(f.key)}
                onChange={(e) => set({ required_special: toggle(c.required_special, f.key, e.target.checked) })}
              />
              {f.label}
            </label>
          ))}
        </div>
      </Row>
      <Row label="个人抬头" {...fin("allow_personal")} note="科研经费报销多要单位抬头和税号；开了以后客人能选「个人」，不用填税号。">
        <label className="flex items-center gap-2 text-sm text-foreground">
          <input type="checkbox" checked={c.allow_personal} onChange={(e) => set({ allow_personal: e.target.checked })} />
          收个人抬头
        </label>
      </Row>
      <Row label="申请期限" {...fin("apply_window_days")} note="订单完成后多少天内能在网上申请；0 = 不限。">
        <input aria-label="申请期限天数" type="number" min={0} className={numCls} value={c.apply_window_days}
          onChange={(e) => set({ apply_window_days: Math.max(0, Number(e.target.value) || 0) })} />
      </Row>
      <Row label="哪些渠道的单能自己申请" note="平台能不能开我们没核实，先只开自有网页；平台单在后台手工录。">
        <div className="flex flex-wrap gap-3 text-sm text-body">
          {Object.entries(data.platforms).map(([k, label]) => (
            <label key={k} className="flex items-center gap-1.5">
              <input type="checkbox" checked={c.eligible_platforms.includes(k)}
                onChange={(e) => set({ eligible_platforms: toggle(c.eligible_platforms, k, e.target.checked) })} />
              {label}
            </label>
          ))}
        </div>
      </Row>
      <Row label="发票备注" note="有的学校报销要在备注里写项目号。">
        <label className="flex items-center gap-2 text-sm text-foreground">
          <input type="checkbox" checked={c.allow_remark} onChange={(e) => set({ allow_remark: e.target.checked })} />
          让客人填备注
        </label>
      </Row>
      <Row label="发票文件" note="上传时按内容认，不只看后缀。">
        <div className="flex flex-wrap items-center gap-3 text-sm text-body">
          {["pdf", "ofd", "xml"].map((t) => (
            <label key={t} className="flex items-center gap-1.5">
              <input type="checkbox" checked={c.file_types.includes(t)} onChange={(e) => set({ file_types: toggle(c.file_types, t, e.target.checked) })} />
              {t.toUpperCase()}
            </label>
          ))}
          <span className="flex items-center gap-1.5">
            单个不超过
            <input aria-label="文件大小上限" type="number" min={1} max={50} className={numCls} value={c.file_max_mb}
              onChange={(e) => set({ file_max_mb: Math.max(1, Number(e.target.value) || 1) })} />
            MB
          </span>
        </div>
      </Row>
      <Row label="给客人看的话" note="核对弹窗、页面提示；通知里能用 {order_no}、{amount}、{reason}、{url}。">
        <textarea aria-label="核对提示" className={areaCls} value={c.customer_notice} onChange={(e) => set({ customer_notice: e.target.value })} />
        <textarea aria-label="开好后怎么拿" className={areaCls} value={c.promise_text} onChange={(e) => set({ promise_text: e.target.value })} />
        <textarea aria-label="开好了的通知" className={areaCls} value={c.notice_issued} onChange={(e) => set({ notice_issued: e.target.value })} />
        <textarea aria-label="驳回的通知" className={areaCls} value={c.notice_rejected} onChange={(e) => set({ notice_rejected: e.target.value })} />
        <textarea aria-label="作废的通知" className={areaCls} value={c.notice_voided} onChange={(e) => set({ notice_voided: e.target.value })} />
      </Row>
      <div className="sticky bottom-0 flex items-center gap-3 border-t bg-background py-3">
        <Button
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            setMsg("");
            try {
              await onSave(c);
              setMsg("存好了");
            } catch (e) {
              setMsg(e instanceof Error ? e.message : "没存上");
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy ? <Loader2 className="animate-spin" /> : null}
          保存
        </Button>
        {msg ? <span className="text-sm text-body">{msg}</span> : null}
      </div>
    </div>
  );
}
