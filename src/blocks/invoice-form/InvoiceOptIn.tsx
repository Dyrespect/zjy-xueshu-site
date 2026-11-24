import { CheckRow } from "@/components/choice";
import type { FieldKey, InvoiceFields, InvoicePublicConfig } from "@/lib/invoice-types";

import { InvoiceFieldsForm } from "./InvoiceFieldsForm";

export interface InvoiceOptInProps {
  config: InvoicePublicConfig;
  want: boolean;
  onWant: (want: boolean) => void;
  value: InvoiceFields;
  onChange: (v: InvoiceFields) => void;
  errors?: Partial<Record<FieldKey | "kind" | "title_kind", string>>;
  /** 跟下单页其他几节一样的编号 */
  no?: string;
}

/** 下单页的「发票」一节：勾「需要发票」就展开表单；不勾也行，付款后在交付页还能补。只吃 props。 */
export function InvoiceOptIn({ config, want, onWant, value, onChange, errors, no = "05" }: InvoiceOptInProps) {
  if (!config.enabled) return null;
  return (
    <section className="flex flex-col gap-3.5" aria-label="发票">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-t pt-4">
        <span className="text-xs font-medium text-muted-foreground tabular-nums">{no}</span>
        <h2 className="text-base font-semibold text-foreground">发票</h2>
        <span className="text-xs text-muted-foreground">报销用，可不选</span>
      </div>
      <CheckRow
        checked={want}
        onChange={onWant}
        title="需要发票"
        note={`${config.kinds.map((k) => k.label).join("、")}，开票金额就是实付金额、不另加税。订单完成（确认收货）后开出，交付页能看进度、下载。`}
      />
      {want ? (
        <div className="rounded-lg border px-4 py-4">
          <InvoiceFieldsForm config={config} value={value} onChange={onChange} errors={errors} idPrefix="order-inv" />
          <p className="mt-3 text-xs leading-relaxed text-muted-foreground">现在不方便填可以先不勾，付款后在交付页「发票」那一块补填。</p>
        </div>
      ) : null}
    </section>
  );
}
