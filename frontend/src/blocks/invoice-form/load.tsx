/**
 * 下单页用：勾「需要发票」的状态、付款前核对、拿到付款页令牌后存预填。
 * OrderPage 里三处：<OrderPicker extra={invoice.section} />、付款前 await invoice.beforePay()、下单后 await invoice.afterCheckout(令牌)。
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { ApiError } from "@/lib/api";
import {
  EMPTY_FIELDS,
  getInvoiceConfig,
  quickCheck,
  saveInvoiceDraft,
  type FieldKey,
  type InvoiceFields,
  type InvoicePublicConfig,
} from "@/lib/invoices";

import { InvoiceConfirmDialog } from "./InvoiceConfirmDialog";
import { InvoiceOptIn } from "./InvoiceOptIn";

const STORE = "xshb.invoice.fields";

function remembered(): InvoiceFields {
  try {
    const raw = window.localStorage.getItem(STORE);
    return raw ? { ...EMPTY_FIELDS, ...(JSON.parse(raw) as Partial<InvoiceFields>) } : EMPTY_FIELDS;
  } catch {
    return EMPTY_FIELDS;
  }
}

export interface CheckoutInvoice {
  /** 放进 OrderPicker 的 extra 插槽 */
  section: ReactNode;
  /** 核对弹窗（放在页面里任意位置） */
  dialog: ReactNode;
  /** 去付款前调：没勾直接 true；勾了先查一遍、弹核对窗，点「核对无误」才 true */
  beforePay: () => Promise<boolean>;
  /** 下单成功拿到付款页令牌后调：存预填。存不上不挡付款，返回一句给客人看的话（空 = 存上了） */
  afterCheckout: (viewToken: string) => Promise<string>;
}

export function useCheckoutInvoice(): CheckoutInvoice {
  const [config, setConfig] = useState<InvoicePublicConfig | null>(null);
  const [want, setWant] = useState(false);
  const [fields, setFields] = useState<InvoiceFields>(remembered);
  const [errors, setErrors] = useState<Partial<Record<FieldKey, string>>>({});
  const [open, setOpen] = useState(false);
  const pending = useRef<((ok: boolean) => void) | null>(null);

  useEffect(() => {
    getInvoiceConfig()
      .then(setConfig)
      .catch(() => setConfig(null)); // 拿不到设置就不出这一节，不挡下单
  }, []);

  const required = useMemo(() => config?.kinds.find((k) => k.key === fields.kind)?.required ?? [], [config, fields.kind]);
  const finish = (ok: boolean) => {
    setOpen(false);
    pending.current?.(ok);
    pending.current = null;
  };

  const beforePay = () => {
    if (!want || !config?.enabled) return Promise.resolve(true);
    const errs = quickCheck(fields, required, config.labels);
    setErrors(errs);
    if (Object.keys(errs).length) {
      document.getElementById(`order-inv-${Object.keys(errs)[0]}`)?.focus();
      return Promise.resolve(false);
    }
    return new Promise<boolean>((resolve) => {
      pending.current = resolve;
      setOpen(true);
    });
  };

  const afterCheckout = async (viewToken: string) => {
    if (!want || !config?.enabled) return "";
    try {
      await saveInvoiceDraft(viewToken, fields);
      try {
        window.localStorage.setItem(STORE, JSON.stringify(fields));
      } catch {
        /* 存不了就下次重填 */
      }
      return "";
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : "发票信息没存上";
      return `${msg}。付款不受影响，付完在交付页补填发票信息就行。`;
    }
  };

  const section = config ? (
    <InvoiceOptIn
      config={config}
      want={want}
      onWant={(v) => {
        setWant(v);
        setErrors({});
      }}
      value={fields}
      onChange={(v) => {
        setFields(v);
        if (Object.keys(errors).length) setErrors({});
      }}
      errors={errors}
    />
  ) : null;

  const dialog = config ? (
    <InvoiceConfirmDialog
      open={open}
      onOpenChange={(v) => (v ? setOpen(true) : finish(false))}
      config={config}
      fields={fields}
      confirmLabel="核对无误，去付款"
      onConfirm={() => finish(true)}
    />
  ) : null;

  return { section, dialog, beforePay, afterCheckout };
}
