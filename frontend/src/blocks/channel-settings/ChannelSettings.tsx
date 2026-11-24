import { Check, Copy, Loader2 } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import type { ChannelOverview, ChannelProduct, ShopStatus } from "@/lib/shop-types";
import { cn } from "@/lib/utils";

export interface NewProduct {
  platform: string;
  product_ref: string;
  title: string;
  sku: string;
  addons: string[];
  listed_price: string;
  note: string;
}

export interface ChannelSettingsProps {
  status: ShopStatus;
  overview: ChannelOverview;
  onSaveProfile: (platform: string, adapter: string, enabled: boolean) => Promise<void>;
  onAddProduct: (body: NewProduct) => Promise<void>;
  onToggleProduct: (p: ChannelProduct) => void;
  onRunTick: () => Promise<string>;
  /** 后台「设置」页地址（改价、改自动确认天数在那边） */
  settingsHref: string;
}

const ADAPTER_LABEL: Record<string, string> = {
  manual_paste: "录单，复制发货文案去平台贴",
  fixed_link: "固定链接：买家填订单号，你核对后发码",
  manual: "录单，复制发货文案发到平台聊天里",
  openapi: "开放平台自动（还没接）",
};
const inputCls = "h-9 rounded-md border border-input bg-background px-2.5 text-sm text-foreground outline-none focus-visible:border-ring";

function H({ children }: { children: string }) {
  return <h2 className="text-base font-semibold text-foreground">{children}</h2>;
}

/** 收款设置：付款方式开没开、缺哪些配置；各渠道怎么收单；平台商品对照（固定链接）；定时任务。只吃 props。 */
export function ChannelSettings(props: ChannelSettingsProps) {
  const { status, overview } = props;
  const [np, setNp] = useState<NewProduct>({ platform: "xhs", product_ref: "", title: "", sku: overview.skus[0]?.sku ?? "", addons: [], listed_price: "", note: "" });
  const [busy, setBusy] = useState("");
  const [msg, setMsg] = useState("");
  const [copied, setCopied] = useState<number | null>(null);
  const label = (platform: string) => overview.profiles.find((p) => p.platform === platform)?.label ?? platform;

  return (
    <div className="flex flex-col gap-10">
      <section className="flex flex-col gap-3">
        <H>自有网页的付款方式</H>
        <p className="text-sm text-body">
          商户号、密钥只在服务器的 .env 里；缺哪项这里就写缺哪项，那种方式不出在下单页。
          {status.fake ? " 现在开着假网关（本机测试用，线上必须关）。" : ""}
          {!status.enabled ? " 总开关关着：下单页显示暂停接单。" : ""}
        </p>
        <div className="overflow-x-auto rounded-lg border">
          <table className="w-full min-w-[560px] text-sm">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="px-4 py-2 font-normal">方式</th>
                <th className="px-4 py-2 font-normal">给谁用</th>
                <th className="px-4 py-2 font-normal">用哪个节点</th>
                <th className="px-4 py-2 font-normal">状态</th>
              </tr>
            </thead>
            <tbody className="divide-y">
              {status.methods.map((m) => (
                <tr key={m.method}>
                  <td className="px-4 py-2.5 text-foreground">{m.label}</td>
                  <td className="px-4 py-2.5 text-body">{m.where}</td>
                  <td className="px-4 py-2.5 font-mono text-xs text-body">{m.node || "—"}</td>
                  <td className={cn("px-4 py-2.5 text-xs", m.ready ? "text-foreground" : "text-muted-foreground")}>
                    {m.ready ? "能用" : !m.node ? "没开" : m.missing.length ? `缺：${m.missing.join("、")}` : "还不能用"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-xs leading-relaxed text-muted-foreground">
          交水印版后 {status.auto_confirm_days} 天没回应自动确认收货（{status.auto_confirm_platforms.join("、")} 的单；天数在
          <a href={props.settingsHref} className="text-primary hover:underline">「设置」</a>里改）。定时任务{status.timer ? `每 ${status.timer_minutes} 分钟跑一次` : "关着"}，
          待付款单 {status.checkout_ttl_min} 分钟过期。
          <button
            type="button"
            className="ml-2 text-primary hover:underline"
            disabled={busy === "tick"}
            onClick={async () => {
              setBusy("tick");
              setMsg(await props.onRunTick());
              setBusy("");
            }}
          >
            现在跑一次
          </button>
        </p>
        {msg ? <p className="text-xs text-foreground">{msg}</p> : null}
      </section>

      <section className="flex flex-col gap-3">
        <H>平台怎么收单</H>
        <ul className="flex flex-col divide-y rounded-lg border">
          {overview.profiles.map((p) => (
            <li key={p.platform} className="flex flex-wrap items-center gap-x-4 gap-y-2 px-4 py-3 text-sm">
              <span className="w-12 font-medium text-foreground">{p.label}</span>
              <select
                aria-label={`${p.label}收单方式`}
                className={cn(inputCls, "min-w-64")}
                value={p.adapter}
                disabled={p.adapters.length < 2 || busy === p.platform}
                onChange={async (e) => {
                  setBusy(p.platform);
                  await props.onSaveProfile(p.platform, e.target.value, p.enabled);
                  setBusy("");
                }}
              >
                {p.adapters.map((a) => (
                  <option key={a} value={a}>{ADAPTER_LABEL[a] ?? a}</option>
                ))}
              </select>
              <label className="inline-flex items-center gap-1.5 text-body">
                <input
                  type="checkbox"
                  checked={p.enabled}
                  disabled={busy === p.platform}
                  onChange={async (e) => {
                    setBusy(p.platform);
                    await props.onSaveProfile(p.platform, p.adapter, e.target.checked);
                    setBusy("");
                  }}
                />
                开着
              </label>
              <span className="text-xs text-muted-foreground">
                付款 {p.remind_after_paid_hours} 小时后还没点「平台已完成」就提醒你 · 发货文案{p.delivery_template === "code_only" ? "只放激活码" : "放激活码和兑换网址"}
              </span>
            </li>
          ))}
        </ul>
      </section>

      <section className="flex flex-col gap-3">
        <H>平台商品</H>
        <p className="text-sm text-body">平台上挂的每个商品对应一个货号（加购也各挂一个）。标价和设置里的价对不上会进「该看一眼」。固定链接方式下，把商品的链接填进平台的发货栏。</p>
        {overview.products.length ? (
          <ul className="flex flex-col divide-y rounded-lg border">
            {overview.products.map((p) => (
              <li key={p.id} className={cn("flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5 text-sm", !p.active && "opacity-50")}>
                <span className="w-12 text-xs text-muted-foreground">{label(p.platform)}</span>
                <span className="text-foreground">{p.title || p.product_ref}</span>
                <span className="text-body">{p.sku_name}</span>
                <span className={cn("text-xs tabular-nums", p.price_ok ? "text-muted-foreground" : "font-medium text-foreground")}>
                  标价 {p.listed_price || "—"}{p.price_ok ? "" : `（设置 ${p.price}）`}
                </span>
                <button
                  type="button"
                  className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
                  onClick={() => navigator.clipboard?.writeText(p.link).then(() => { setCopied(p.id); window.setTimeout(() => setCopied(null), 1500); })}
                >
                  {copied === p.id ? <Check className="size-3" /> : <Copy className="size-3" />}
                  {copied === p.id ? "复制好了" : "复制固定链接"}
                </button>
                <button type="button" className="ml-auto text-xs text-muted-foreground hover:text-foreground" onClick={() => props.onToggleProduct(p)}>
                  {p.active ? "下架" : "上架"}
                </button>
              </li>
            ))}
          </ul>
        ) : null}
        <div className="flex flex-wrap items-end gap-3 rounded-lg border p-4">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">渠道</span>
            <select aria-label="商品渠道" className={inputCls} value={np.platform} onChange={(e) => setNp({ ...np, platform: e.target.value })}>
              {overview.profiles.map((p) => (
                <option key={p.platform} value={p.platform}>{p.label}</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">平台上的商品 id（或好认的名字）</span>
            <input aria-label="商品 id" className={inputCls} value={np.product_ref} onChange={(e) => setNp({ ...np, product_ref: e.target.value })} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">后台看的名字</span>
            <input aria-label="商品名字" className={inputCls} value={np.title} onChange={(e) => setNp({ ...np, title: e.target.value })} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">货号</span>
            <select aria-label="商品货号" className={inputCls} value={np.sku} onChange={(e) => setNp({ ...np, sku: e.target.value })}>
              {overview.skus.map((s) => (
                <option key={s.sku} value={s.sku}>{s.name}（{s.price} 元）</option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">平台上标的价</span>
            <input aria-label="平台标价" className={cn(inputCls, "w-24")} value={np.listed_price} inputMode="decimal" onChange={(e) => setNp({ ...np, listed_price: e.target.value })} />
          </label>
          <Button
            disabled={!np.product_ref.trim() || busy === "add"}
            onClick={async () => {
              setBusy("add");
              try {
                await props.onAddProduct(np);
                setNp({ ...np, product_ref: "", title: "", listed_price: "" });
              } finally {
                setBusy("");
              }
            }}
          >
            {busy === "add" ? <Loader2 className="animate-spin" /> : null}
            登记商品
          </Button>
        </div>
      </section>
    </div>
  );
}
