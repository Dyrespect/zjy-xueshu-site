import { Loader2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { ClaimProduct, ClaimView } from "@/lib/shop-types";

export interface ClaimFormProps {
  product: ClaimProduct;
  /** 提交过以后的状态（pending / rejected / problem / exists）；ok 时页面换成激活码那一块 */
  state: ClaimView | null;
  onSubmit: (orderNo: string) => void;
  submitting?: boolean;
  error?: string;
}

/** 平台商品的固定链接页：买家填平台订单号 → 等负责人核对 → 页面自己刷出激活码。只吃 props。 */
export function ClaimForm({ product, state, onSubmit, submitting, error }: ClaimFormProps) {
  const [no, setNo] = useState("");
  if (!product.ok) {
    return (
      <div className="mx-auto max-w-xl px-4 py-16 sm:px-6">
        <h1 className="font-display text-3xl leading-tight font-bold tracking-wide text-foreground">链接用不了</h1>
        <p className="mt-2 text-sm text-body">{product.why || "这个商品可能下架了。"} 回到下单的平台，在订单里联系我们。</p>
      </div>
    );
  }
  const waiting = state?.status === "pending";
  return (
    <div className="mx-auto flex max-w-xl flex-col gap-6 px-4 py-10 sm:px-6">
      <div className="flex flex-col gap-1">
        <h1 className="font-display text-3xl leading-tight font-bold tracking-wide text-foreground">领激活码</h1>
        <p className="text-sm text-body">
          {product.platform_label}商品：{product.title || product.sku_name}（{product.sku_name}）
        </p>
      </div>
      {waiting ? (
        <div className="flex flex-col items-center gap-3 rounded-lg border px-5 py-8 text-center" aria-live="polite">
          <Loader2 className="size-5 animate-spin text-muted-foreground" />
          <p className="text-sm text-foreground">{state?.message || "正在核对订单号"}</p>
          <p className="text-xs text-muted-foreground">可以先去忙别的，回来再打开这个链接</p>
        </div>
      ) : (
        <form
          className="flex flex-col gap-3 rounded-lg border px-5 py-6"
          onSubmit={(e) => {
            e.preventDefault();
            if (no.trim()) onSubmit(no.trim());
          }}
        >
          <label className="flex flex-col gap-1.5">
            <span className="text-sm font-medium text-foreground">{product.platform_label}订单号</span>
            <span className="text-xs text-muted-foreground">在{product.platform_label}的订单详情里，复制「订单号」那一串数字</span>
            <Input value={no} onChange={(e) => setNo(e.target.value)} inputMode="text" autoComplete="off" className="h-11 text-base" />
          </label>
          {state && state.status !== "pending" && state.message ? <p className="text-sm text-foreground">{state.message}</p> : null}
          {error ? <p className="text-sm text-destructive">{error}</p> : null}
          <Button type="submit" size="lg" className="h-11" disabled={!no.trim() || submitting}>
            {submitting ? <Loader2 className="animate-spin" /> : null}
            提交
          </Button>
        </form>
      )}
      <p className="text-xs leading-relaxed text-muted-foreground">
        订单号由负责人对上平台里的真实订单后才发激活码，一般几分钟；一个订单号只能领一次。
      </p>
    </div>
  );
}
