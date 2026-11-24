/**
 * 交付页、付款结果页里的「发票」一块：取数、提交、撤回都在这里，区块本身只吃 props。
 * DeliveryPage：<DeliveryInvoice token={交付页令牌} />；PayPage：<PayInvoice token={付款页令牌} />。
 */
import { useCallback, useEffect, useState } from "react";

import { ApiError } from "@/lib/api";
import {
  applyCheckoutInvoice,
  applyDeliveryInvoice,
  getCheckoutInvoice,
  getDeliveryInvoice,
  withdrawCheckoutInvoice,
  withdrawDeliveryInvoice,
  type InvoiceFields,
  type InvoicePanelData,
  type InvoiceSubmitResult,
} from "@/lib/invoices";

import { InvoiceFieldError, InvoicePanel } from "./InvoicePanel";

function rethrow(e: unknown): never {
  if (e instanceof ApiError) {
    const field = e.detail && typeof e.detail === "object" && "field" in e.detail ? String((e.detail as { field: unknown }).field ?? "") : "";
    throw new InvoiceFieldError(e.message, field);
  }
  throw e;
}

function useInvoice(load: () => Promise<InvoicePanelData>) {
  const [data, setData] = useState<InvoicePanelData | null>(null);
  const reload = useCallback(() => load().then(setData, () => setData(null)), [load]);
  useEffect(() => {
    void reload();
  }, [reload]);
  return { data, reload };
}

function Connected({
  load,
  apply,
  withdraw,
  variant,
}: {
  load: () => Promise<InvoicePanelData>;
  apply: (f: InvoiceFields) => Promise<InvoiceSubmitResult>;
  withdraw: (id: number) => Promise<InvoiceSubmitResult>;
  variant: "delivery" | "pay";
}) {
  const { data, reload } = useInvoice(load);
  if (!data) return null;
  return (
    <InvoicePanel
      key={`${data.current?.id ?? "none"}-${data.current?.step ?? ""}`}
      data={data}
      variant={variant}
      onApply={async (f) => {
        const r = await apply(f).catch(rethrow);
        await reload();
        return r.exit === "exists" ? r.note || "这单已经申请过了" : r.note || "提交了";
      }}
      onWithdraw={async (id) => {
        const r = await withdraw(id).catch(rethrow);
        await reload();
        return r.note || "撤回了";
      }}
    />
  );
}

export function DeliveryInvoice({ token }: { token: string }) {
  const load = useCallback(() => getDeliveryInvoice(token), [token]);
  const apply = useCallback((f: InvoiceFields) => applyDeliveryInvoice(token, f), [token]);
  const withdraw = useCallback((id: number) => withdrawDeliveryInvoice(token, id), [token]);
  return <Connected load={load} apply={apply} withdraw={withdraw} variant="delivery" />;
}

export function PayInvoice({ token }: { token: string }) {
  const load = useCallback(() => getCheckoutInvoice(token), [token]);
  const apply = useCallback((f: InvoiceFields) => applyCheckoutInvoice(token, f), [token]);
  const withdraw = useCallback((id: number) => withdrawCheckoutInvoice(token, id), [token]);
  return <Connected load={load} apply={apply} withdraw={withdraw} variant="pay" />;
}
