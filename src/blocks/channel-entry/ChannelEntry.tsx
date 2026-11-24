import { Check, Copy, Loader2 } from "lucide-react";
import { useMemo, useState } from "react";

import { Button } from "@/components/ui/button";
import type { ChannelOverview, ManualEntryBody, ManualEntryResult } from "@/lib/shop-types";
import { cn } from "@/lib/utils";

export interface ChannelEntryProps {
  overview: ChannelOverview;
  onSubmit: (body: ManualEntryBody) => Promise<ManualEntryResult>;
  onPasted: (inboxId: number) => void;
}

const inputCls = "h-9 rounded-md border border-input bg-background px-2.5 text-sm text-foreground outline-none focus-visible:border-ring";

/** 人工录单：选渠道 → 选商品（或直接选货号）→ 填平台订单号 → 出一句发货文案，复制去平台贴。只吃 props。 */
export function ChannelEntry({ overview, onSubmit, onPasted }: ChannelEntryProps) {
  const manual = overview.profiles.filter((p) => p.enabled && p.mode !== "verify_then_create" && p.adapter !== "openapi");
  const [platform, setPlatform] = useState(manual[0]?.platform ?? "");
  const products = useMemo(() => overview.products.filter((p) => p.platform === platform && p.active), [overview.products, platform]);
  const [productId, setProductId] = useState<string>("");
  const [sku, setSku] = useState(overview.skus.find((s) => !s.sku.startsWith("addon-"))?.sku ?? "");
  const [addons, setAddons] = useState<string[]>([]);
  const [no, setNo] = useState("");
  const [amount, setAmount] = useState("");
  const [buyer, setBuyer] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState("");
  const [result, setResult] = useState<ManualEntryResult | null>(null);
  const [copied, setCopied] = useState(false);
  const [pasted, setPasted] = useState(false);

  if (!manual.length) {
    return <p className="rounded-lg border px-4 py-6 text-sm text-muted-foreground">现在没有要人工录单的渠道（固定链接的单在「该看一眼」里核对）。</p>;
  }

  const submit = async () => {
    setBusy(true);
    setErr("");
    setResult(null);
    setPasted(false);
    try {
      const body: ManualEntryBody = { platform, platform_order_id: no.trim(), paid_amount: amount.trim(), buyer_hint: buyer.trim() };
      if (productId) body.product_id = Number(productId);
      else Object.assign(body, { sku, addons });
      const r = await onSubmit(body);
      setResult(r);
      if (r.exit !== "manual" && r.exit !== "exists") setErr(r.detail);
    } catch (e) {
      setErr(e instanceof Error ? e.message : "没录成");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <p className="text-sm leading-relaxed text-body">
        在平台 App 里看到一单，就在这里录：出来的一句发货文案（激活码 + 兑换网址）复制去平台订单里发货。同一个订单号录两次给的是同一枚码。
      </p>
      <div className="grid gap-4 sm:grid-cols-2 lg:max-w-3xl">
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">渠道</span>
          <select aria-label="渠道" className={inputCls} value={platform} onChange={(e) => { setPlatform(e.target.value); setProductId(""); }}>
            {manual.map((p) => (
              <option key={p.platform} value={p.platform}>{p.label}</option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">卖的是哪个商品</span>
          <select aria-label="商品" className={inputCls} value={productId} onChange={(e) => setProductId(e.target.value)}>
            <option value="">直接选货号</option>
            {products.map((p) => (
              <option key={p.id} value={p.id}>{p.title || p.product_ref}（{p.sku_name}）</option>
            ))}
          </select>
        </label>
        {!productId ? (
          <>
            <label className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">货号</span>
              <select aria-label="货号" className={inputCls} value={sku} onChange={(e) => setSku(e.target.value)}>
                {overview.skus.map((s) => (
                  <option key={s.sku} value={s.sku}>{s.name}（{s.price} 元）</option>
                ))}
              </select>
            </label>
            <div className="flex flex-col gap-1">
              <span className="text-xs text-muted-foreground">同一笔买的加购</span>
              <div className="flex min-h-9 flex-wrap items-center gap-x-4 gap-y-1">
                {overview.addons.map((a) => (
                  <label key={a.key} className="inline-flex items-center gap-1.5 text-sm text-body">
                    <input
                      type="checkbox"
                      checked={addons.includes(a.key)}
                      onChange={(e) => setAddons(e.target.checked ? [...addons, a.key] : addons.filter((k) => k !== a.key))}
                    />
                    {a.name}
                  </label>
                ))}
              </div>
            </div>
          </>
        ) : null}
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">平台订单号</span>
          <input aria-label="平台订单号" className={inputCls} value={no} onChange={(e) => setNo(e.target.value)} placeholder="订单详情里那一串" />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-xs text-muted-foreground">实付（可空，空 = 按商品标价）</span>
          <input aria-label="实付" className={inputCls} value={amount} onChange={(e) => setAmount(e.target.value)} inputMode="decimal" />
        </label>
        <label className="flex flex-col gap-1 sm:col-span-2 sm:max-w-sm">
          <span className="text-xs text-muted-foreground">买家的平台号（可空；用来认退款过很多次的买家，号能改，只当参考）</span>
          <input aria-label="买家的平台号" className={inputCls} value={buyer} onChange={(e) => setBuyer(e.target.value)} />
        </label>
      </div>
      <div>
        <Button disabled={busy || no.trim().length < 3} onClick={submit}>
          {busy ? <Loader2 className="animate-spin" /> : null}
          录单，出发货文案
        </Button>
        {err ? <p className="mt-2 text-sm text-destructive">{err}</p> : null}
      </div>
      {result && result.text ? (
        <div className="flex flex-col gap-3 rounded-lg border p-4 lg:max-w-3xl" data-testid="delivery-text">
          <div className="flex items-center justify-between gap-3">
            <span className="text-sm font-medium text-foreground">{result.exit === "exists" ? "这个订单号录过了，还是这一句" : "复制这一句，贴到平台订单的发货栏"}</span>
            <span className="text-xs text-muted-foreground">单号 #{result.order_id}</span>
          </div>
          <pre className="rounded-md bg-card px-3 py-2.5 font-sans text-sm leading-relaxed whitespace-pre-wrap text-foreground">{result.text}</pre>
          <div className="flex gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => navigator.clipboard?.writeText(result.text).then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 1500); })}
            >
              {copied ? <Check /> : <Copy />}
              {copied ? "复制好了" : "复制"}
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={pasted || !result.inbox_id}
              className={cn(pasted && "text-muted-foreground")}
              onClick={() => { if (result.inbox_id) { onPasted(result.inbox_id); setPasted(true); } }}
            >
              {pasted ? "记下了" : "贴好了"}
            </Button>
          </div>
        </div>
      ) : null}
    </div>
  );
}
