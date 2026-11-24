import { Input } from "@/components/ui/input";
import type { FieldKey, InvoiceFields, InvoicePublicConfig } from "@/lib/invoice-types";
import { FIELD_ORDER } from "@/lib/invoice-types";
import { cn } from "@/lib/utils";

export interface InvoiceFieldsFormProps {
  config: InvoicePublicConfig;
  value: InvoiceFields;
  onChange: (v: InvoiceFields) => void;
  /** 哪个字段不对（前端先查的，或后端退回来的） */
  errors?: Partial<Record<FieldKey | "kind" | "title_kind", string>>;
  /** 给每个输入框的 id 加前缀（一页里有两份表单时不撞） */
  idPrefix?: string;
}

const HINTS: Partial<Record<FieldKey, string>> = {
  title: "单位全称，和单位财务给的一字不差（例：XX大学）",
  tax_id: "统一社会信用代码，一般 18 位，找单位财务要",
  email: "发票开好会发到这里",
  bank_account: "只填数字",
  remark: "有的学校报销要在备注写项目号",
};

const PLACEHOLDER: Partial<Record<FieldKey, string>> = {
  title: "单位全称",
  tax_id: "18 位统一社会信用代码",
  email: "name@example.edu.cn",
  phone: "区号-电话",
};

function Choice({ options, value, onChange, label }: { options: { key: string; label: string }[]; value: string; onChange: (k: string) => void; label: string }) {
  return (
    <div role="radiogroup" aria-label={label} className="flex flex-wrap gap-2">
      {options.map((o) => (
        <button
          key={o.key}
          type="button"
          role="radio"
          aria-checked={o.key === value}
          onClick={() => onChange(o.key)}
          className={cn(
            "rounded-md border px-3 py-1.5 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/40",
            o.key === value ? "border-primary bg-highlight/40 text-foreground" : "bg-background text-body hover:border-faint",
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

/** 发票信息表单：发票类型、抬头类型（设置开了才出）、按类型要填的几项。只吃 props，校验在页面 / 后端。 */
export function InvoiceFieldsForm({ config, value: v, onChange, errors = {}, idPrefix = "inv" }: InvoiceFieldsFormProps) {
  const kind = config.kinds.find((k) => k.key === v.kind) ?? config.kinds[0];
  const required = new Set<FieldKey>((kind?.required ?? []).filter((k) => !(v.title_kind === "personal" && k === "tax_id")));
  const show = FIELD_ORDER.filter((k) => required.has(k) || (k === "remark" && config.allow_remark) || (k === "tax_id" && v.title_kind === "unit"));
  const set = (patch: Partial<InvoiceFields>) => onChange({ ...v, ...patch });
  return (
    <div className="flex flex-col gap-4">
      {config.kinds.length > 1 ? (
        <div className="flex flex-col gap-1.5">
          <span className="text-sm font-medium text-foreground">发票类型</span>
          <Choice label="发票类型" options={config.kinds} value={v.kind} onChange={(k) => set({ kind: k as InvoiceFields["kind"], title_kind: "unit" })} />
          {errors.kind ? <span className="text-xs text-destructive">{errors.kind}</span> : null}
        </div>
      ) : null}
      {config.allow_personal && v.kind === "normal" ? (
        <div className="flex flex-col gap-1.5">
          <span className="text-sm font-medium text-foreground">抬头类型</span>
          <Choice
            label="抬头类型"
            options={[
              { key: "unit", label: "单位" },
              { key: "personal", label: "个人" },
            ]}
            value={v.title_kind}
            onChange={(k) => set({ title_kind: k as InvoiceFields["title_kind"] })}
          />
        </div>
      ) : null}
      <div className="grid gap-4 sm:grid-cols-2">
        {show.map((k) => {
          const id = `${idPrefix}-${k}`;
          const label = k === "title" && v.title_kind === "personal" ? "抬头（姓名）" : (config.labels[k] ?? k);
          const wide = k === "title" || k === "address" || k === "remark";
          return (
            <label key={k} htmlFor={id} className={cn("flex flex-col gap-1.5", wide && "sm:col-span-2")}>
              <span className="text-sm font-medium text-foreground">
                {label}
                {required.has(k) ? null : <span className="ml-1 text-xs font-normal text-muted-foreground">选填</span>}
              </span>
              <Input
                id={id}
                aria-label={label}
                aria-invalid={errors[k] ? true : undefined}
                value={v[k]}
                placeholder={PLACEHOLDER[k]}
                inputMode={k === "email" ? "email" : k === "bank_account" || k === "phone" ? "tel" : "text"}
                autoComplete={k === "email" ? "email" : "off"}
                className={cn("h-10 text-base", k === "tax_id" && "font-mono tracking-wide uppercase")}
                onChange={(e) => set({ [k]: e.target.value } as Partial<InvoiceFields>)}
              />
              {errors[k] ? (
                <span className="text-xs text-destructive">{errors[k]}</span>
              ) : HINTS[k] ? (
                <span className="text-xs text-muted-foreground">{HINTS[k]}</span>
              ) : null}
            </label>
          );
        })}
      </div>
    </div>
  );
}
