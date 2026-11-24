import { useCallback, useEffect, useState } from "react";
import { useParams } from "react-router";

import { ClaimForm } from "@/blocks/claim-form";
import { OrderPaid } from "@/blocks/order-paid";
import { SiteFrame } from "@/blocks/site-shell/load";
import {
  getClaimProduct,
  getClaimStatus,
  rememberClaim,
  rememberedClaim,
  submitClaim,
  type ClaimProduct,
  type ClaimView,
} from "@/lib/shop";

/** /x/:token 平台商品的固定链接页：填平台订单号 → 负责人核对 → 自己刷出激活码。提交凭据记在本机，关了再开还能看到。 */
export function ClaimPage() {
  const { token = "" } = useParams();
  const [product, setProduct] = useState<ClaimProduct | null>(null);
  const [state, setState] = useState<ClaimView | null>(null);
  const [claimToken, setClaimToken] = useState<string | null>(() => rememberedClaim(token));
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    getClaimProduct(token)
      .then(setProduct)
      .catch(() => setProduct({ ok: false, platform: "", platform_label: "", title: "", sku_name: "", why: "这个链接现在用不了" }));
  }, [token]);

  const poll = useCallback(() => {
    if (!claimToken) return;
    getClaimStatus(claimToken)
      .then(setState)
      .catch(() => undefined);
  }, [claimToken]);
  useEffect(poll, [poll]);
  useEffect(() => {
    if (!claimToken || (state && state.status !== "pending")) return;
    const t = window.setInterval(poll, 5000);
    return () => window.clearInterval(t);
  }, [claimToken, state, poll]);

  const submit = (no: string) => {
    setSubmitting(true);
    setError("");
    submitClaim(token, no)
      .then((v) => {
        if (v.claim_token) {
          rememberClaim(token, v.claim_token);
          setClaimToken(v.claim_token);
        }
        setState(v.status === "exists" ? { ...v, status: "exists" } : v);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "没提交上，再试一次"))
      .finally(() => setSubmitting(false));
  };

  return (
    <SiteFrame gate={false} noindex cta={false} className="text-base">
      {!product ? (
        <p className="mx-auto max-w-xl px-4 py-16 text-sm text-muted-foreground sm:px-6">加载中……</p>
      ) : state?.status === "ok" && state.code ? (
        <OrderPaid code={state.code} redeemUrl={state.redeem_url || "/chat"} title="订单号核对好了" summary={product.sku_name} />
      ) : (
        <ClaimForm product={product} state={state} onSubmit={submit} submitting={submitting} error={error} />
      )}
    </SiteFrame>
  );
}
