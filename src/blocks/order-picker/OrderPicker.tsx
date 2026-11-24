import { ExternalLink, Loader2 } from "lucide-react";
import type { ReactNode } from "react";

import { CheckRow, ChoiceCard, Segmented, Stepper } from "@/components/choice";
import { Button } from "@/components/ui/button";
import type { OrderSelection, ShopCatalog, ShopQuote } from "@/lib/shop-types";
import { cn } from "@/lib/utils";

import { type PhoneFallback, PhonePay } from "./PhonePay";

export interface OrderPickerProps {
  catalog: ShopCatalog;
  selection: OrderSelection;
  onChange: (s: OrderSelection) => void;
  /** 后端报的价（金额只认它） */
  quote: ShopQuote | null;
  quoting?: boolean;
  method: string;
  onMethod: (m: string) => void;
  onPay: () => void;
  paying?: boolean;
  error?: string;
  /** 插在「怎么付」后面的一节（开票：需要发票）；不给就没有 */
  extra?: ReactNode;
  /** 付款按钮正上方：付款前要勾的确认（官网整合：协议、AI 处理和出境、定制不退）；不给就没有 */
  consent?: ReactNode;
  /** 页头下面：下单前准备好这些（资料清单，按场合）；不给就没有 */
  prepare?: ReactNode;
  /**
   * 自有网页暂不收款（catalog.pay_mode = platforms，商户号没下来）：「去付款」换成这一块——一句话 + 两个平台的店铺。
   * 链接空着就只显示平台名字。不给就按正常付款显示。
   */
  platform?: PlatformShops;
  /**
   * 手机上这里还不能直接付（微信 H5 没开、或者微信里付款也没开）：「去付款」换成这一块——一句话 + 复制网址到微信里打开 + 去闲鱼下单。
   * 不给就按正常显示。
   */
  phone?: PhoneFallback;
}

export interface PlatformShop {
  label: string;
  /** 店铺链接；空 = 只显示文字 */
  url: string;
}

export interface PlatformShops {
  /** 「现在请在小红书或闲鱼下单，付款后会收到兑换码」（后端给的 catalog.hint） */
  hint: string;
  shops: PlatformShop[];
  /** 怎么找到店（后台「官网」设置里填的一句）；空 = 不显示 */
  note?: string;
}

/** 去平台下单那一块（摘要卡里替代「去付款」） */
function PlatformBlock({ platform }: { platform: PlatformShops }) {
  return (
    <div className="flex flex-col gap-3 rounded-md border px-4 py-3.5" data-testid="order-platforms" data-platforms>
      <p className="text-[15px] font-medium leading-relaxed text-foreground">{platform.hint}</p>
      <ul className="grid grid-cols-2 gap-2.5">
        {platform.shops.map((s) => (
          <li key={s.label}>
            {s.url ? (
              <a
                href={s.url}
                target="_blank"
                rel="noopener noreferrer"
                className="flex h-10 items-center justify-center gap-1.5 rounded-md bg-primary px-3 text-sm font-medium text-primary-foreground hover:bg-primary-hover"
              >
                去{s.label}下单
                <ExternalLink className="size-3.5" aria-hidden />
              </a>
            ) : (
              <span className="flex h-10 items-center justify-center rounded-md border px-3 text-sm font-medium text-foreground">{s.label}</span>
            )}
          </li>
        ))}
      </ul>
      {platform.note ? <p className="text-xs leading-relaxed text-muted-foreground">{platform.note}</p> : null}
      <p className="text-xs leading-relaxed text-muted-foreground">价格和这里一样；拿到兑换码后打开兑换网址认领订单，再交材料。</p>
    </div>
  );
}

function scrollToBlock(attr: string) {
  const el = [...document.querySelectorAll<HTMLElement>(`[${attr}]`)].find((x) => x.offsetParent !== null);
  el?.scrollIntoView({ behavior: "smooth", block: "center" });
}

const WEEK = "日一二三四五六";

export function fmtDay(iso: string | null | undefined): string {
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  return `${m}月${d}日（周${WEEK[dt.getDay()]}）`;
}

function Section({ no, title, hint, children }: { no: string; title: string; hint?: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3.5">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-t pt-4">
        <span className="text-xs font-medium text-muted-foreground tabular-nums">{no}</span>
        <h2 className="text-base font-semibold text-foreground">{title}</h2>
        {hint ? <span className="text-xs text-muted-foreground">{hint}</span> : null}
      </div>
      {children}
    </section>
  );
}

/**
 * 下单页（淘宝式）：选时长档 → 选篇数 → 勾加购 → 看价（后端报的）→ 选付款方式 → 去付款。
 * 只吃 props：价目、报价、付款方式都是页面从接口拿来给的；这里不算钱。
 */
export function OrderPicker(props: OrderPickerProps) {
  const { catalog, selection: sel, onChange, quote, quoting, method, onMethod, onPay, paying, error, extra, consent, platform, phone, prepare } = props;
  const tier = catalog.tiers.find((t) => t.key === sel.tier) ?? catalog.tiers[0];
  const addon = (k: string) => catalog.addons.find((a) => a.key === k && a.price);
  const rush = addon("rush");
  const refs = addon("find_refs");
  const rev = addon("revision");
  const set = (patch: Partial<OrderSelection>) => onChange({ ...sel, ...patch });
  const pickTier = (key: string) => {
    const t = catalog.tiers.find((x) => x.key === key);
    if (!t) return;
    const band = t.prices[sel.band] ? sel.band : (catalog.bands.find((b) => t.prices[b.key])?.key ?? sel.band);
    onChange({ ...sel, tier: key, band, rush: sel.rush && t.rush });
  };
  const rushOff = !tier?.rush ? "这一档不开放加急" : sel.find_refs ? "加急不能和帮我找文献一起选" : "";
  // 帮我找文献按 1 篇的价算，不叠多篇（Edison 11-21）
  const firstBand = catalog.bands[0]?.key ?? sel.band;
  const canPay = catalog.enabled && !!quote?.ok && !!method && !quote?.queue_full && !paying;

  const summary = (
    <div className="flex flex-col gap-4 rounded-lg border p-5">
      <div className="flex flex-col gap-1">
        <span className="text-xs text-muted-foreground">你选的</span>
        <span className="text-base font-semibold text-foreground">{quote?.ok ? quote.sku_name : `${tier?.name ?? ""}`}</span>
      </div>
      {quote?.ok ? (
        <dl className="flex flex-col gap-1.5 text-sm">
          <div className="flex justify-between gap-3">
            <dt className="text-body">基础价（含 {catalog.revisions_included} 轮修改）</dt>
            <dd className="text-foreground tabular-nums">{quote.base_price} 元</dd>
          </div>
          {quote.addons.map((a) => (
            <div key={a.key} className="flex justify-between gap-3">
              <dt className="text-body">{a.name}</dt>
              <dd className="text-foreground tabular-nums">+{a.price} 元</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="text-sm text-muted-foreground">{quote?.why || (quoting ? "在算价……" : "选好档位就出价")}</p>
      )}
      <div className="flex items-baseline justify-between border-t pt-3">
        <span className="text-sm text-body">合计</span>
        {quote?.ok ? (
          <span className="text-2xl font-semibold text-price tabular-nums" data-testid="order-total">
            {quote.total}
            <span className="ml-0.5 text-sm font-normal">元</span>
          </span>
        ) : (
          <span className="text-sm text-muted-foreground">{quoting ? "在算价……" : "还没出价"}</span>
        )}
      </div>
      {quote?.ok ? (
        <ul className="flex flex-col gap-1 text-xs leading-relaxed text-muted-foreground">
          <li>开工后 {quote.hours} 小时内交水印版；内容页 {quote.max_pages} 页以内</li>
          {quote.queue_full ? (
            <li className="text-foreground">往后几天的名额都排满了，暂时不能下单</li>
          ) : quote.earliest_start ? (
            <li>
              按现在的排队，最早 {fmtDay(quote.earliest_start)} 开工，预计 {fmtDay(quote.eta_date)} 交第一版
            </li>
          ) : null}
        </ul>
      ) : null}
      {platform ? (
        <PlatformBlock platform={platform} />
      ) : phone ? (
        <PhonePay fallback={phone} />
      ) : (
        <>
          {consent ? <div data-consent className="scroll-mt-24 border-t pt-3">{consent}</div> : null}
          <Button size="lg" className="h-11 w-full text-[15px]" disabled={!canPay} onClick={onPay}>
            {paying ? <Loader2 className="animate-spin" /> : null}
            去付款
          </Button>
          {error ? <p className="text-sm text-destructive">{error}</p> : null}
        </>
      )}
      <ul className="flex flex-col gap-1.5 border-t pt-3 text-xs leading-relaxed text-muted-foreground">
        {catalog.notices.map((n) => (
          <li key={n}>{n}</li>
        ))}
      </ul>
    </div>
  );

  return (
    <div className="mx-auto max-w-6xl px-4 pt-8 pb-28 sm:px-6 lg:pb-16">
      <h1 className="font-display text-3xl leading-tight font-bold tracking-wide text-foreground sm:text-4xl">下单</h1>
      <p className="mt-2 max-w-2xl text-sm leading-relaxed text-body">
        按汇报时长选档，按材料篇数定价，含 {catalog.revisions_included} 轮修改。{catalog.page_rule_text}。
      </p>
      <p className="mt-1.5 max-w-2xl text-sm leading-relaxed text-body" data-testid="order-brief-note">
        付款后我们会一步步引导你说清楚需求，不用提前想好
      </p>
      {prepare ? <div className="mt-4 max-w-2xl">{prepare}</div> : null}
      {!catalog.enabled ? <p className="mt-4 rounded-md border px-4 py-3 text-sm text-foreground">暂停接单，过一阵再来。</p> : null}

      <div className="mt-8 grid gap-10 lg:grid-cols-[minmax(0,1fr)_340px]">
        <div className="flex flex-col gap-9">
          <Section no="01" title="汇报讲多久" hint="按时长选档">
            <div role="radiogroup" aria-label="时长档" className="grid grid-cols-2 gap-3">
              {catalog.tiers.map((t) => (
                <ChoiceCard key={t.key} selected={t.key === sel.tier} onSelect={() => pickTier(t.key)}>
                  <span className="text-base font-semibold text-foreground">{t.name}</span>
                  <span className="mt-0.5 text-sm text-body tabular-nums">
                    {t.min_minutes}–{t.max_minutes} 分钟
                  </span>
                  <span className="mt-2 text-xs leading-relaxed text-muted-foreground">
                    {t.max_pages} 页以内 · 标准 {t.std_hours} 小时交水印版
                  </span>
                  <span className="mt-2 text-sm text-foreground tabular-nums">
                    {Object.values(t.prices).find(Boolean)} 元起
                  </span>
                </ChoiceCard>
              ))}
            </div>
          </Section>

          <Section no="02" title="要讲几篇材料" hint="论文、开题报告这类主材料">
            <Segmented
              label="篇数"
              value={sel.band}
              onChange={(band) => set({ band })}
              options={catalog.bands.map((b) => ({
                value: b.key,
                label: b.name,
                sub: tier?.prices[b.key] ? `${tier.prices[b.key]} 元` : "不开放",
                disabled: !tier?.prices[b.key] || (sel.find_refs && b.key !== firstBand),
                disabledReason: !tier?.prices[b.key] ? `${tier?.name ?? ""}档不开放${b.name}` : "帮我找文献按 1 篇的价算，找到几篇都含在里面",
              }))}
            />
          </Section>

          <Section no="03" title="加购" hint="可不选">
            <div className="flex flex-col gap-2.5">
              {rush ? (
                <CheckRow
                  checked={sel.rush}
                  disabled={!!rushOff}
                  onChange={(v) => set({ rush: v })}
                  title="加急"
                  note={rushOff || `开工后 ${tier?.rush_hours ?? ""} 小时内交水印版。${rush.note}`}
                  aside={`+${rush.price} 元`}
                />
              ) : null}
              {refs ? (
                <CheckRow
                  checked={sel.find_refs}
                  onChange={(v) => set({ find_refs: v, rush: v ? false : sel.rush, band: v ? firstBand : sel.band })}
                  title={refs.name}
                  note={`没有现成文献时用：你给方向和关键词，我们找文献再做。按 1 篇的价算，找到几篇都含在里面；时限加 ${catalog.find_refs_extra_hours} 小时，不能加急。`}
                  aside={`+${refs.price} 元`}
                />
              ) : null}
              {rev ? (
                <div className={cn("flex items-center gap-3 rounded-lg border bg-background px-3.5 py-3", sel.extra_revisions > 0 && "border-primary bg-highlight/40")}>
                  <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                    <span className="text-sm font-medium text-foreground">{rev.name}</span>
                    <span className="text-xs leading-relaxed text-muted-foreground">
                      基础价含 {catalog.revisions_included} 轮；每多一轮 +{rev.price} 元
                    </span>
                  </span>
                  <Stepper label={rev.name} value={sel.extra_revisions} onChange={(n) => set({ extra_revisions: n })} />
                </div>
              ) : null}
            </div>
          </Section>

          <Section no="04" title="怎么付">
            {platform ? (
              <p className="rounded-md border px-4 py-3 text-sm leading-relaxed text-body">
                {platform.hint}。先在这里选好档位、看清价格，再去平台下同样的那一档。
              </p>
            ) : phone ? (
              <p className="rounded-md border px-4 py-3 text-sm leading-relaxed text-body">
                {phone.copyUrl ? "手机浏览器里还不能直接付。先在这里选好档位、看清价格，再复制网址到微信里打开付（下面有按钮）。" : phone.hint}
              </p>
            ) : catalog.methods.length ? (
              <div role="radiogroup" aria-label="付款方式" className="grid grid-cols-2 gap-3 sm:max-w-md">
                {catalog.methods.map((m) => (
                  <ChoiceCard key={m.method} selected={m.method === method} onSelect={() => onMethod(m.method)} className="py-3">
                    <span className="text-sm font-medium text-foreground">{m.label}</span>
                  </ChoiceCard>
                ))}
              </div>
            ) : (
              <p className="rounded-md border px-4 py-3 text-sm leading-relaxed text-body">{catalog.hint || "付款还没开通"}</p>
            )}
          </Section>

          {extra}

          <div className="lg:hidden">{summary}</div>
        </div>
        <aside className="hidden self-start lg:sticky lg:top-6 lg:block">{summary}</aside>
      </div>

      <div className="fixed inset-x-0 bottom-0 z-10 border-t bg-background px-4 py-3 lg:hidden">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4">
          {quote?.ok ? (
            <span className="text-sm text-body">
              合计 <span className="text-xl font-semibold text-price tabular-nums">{quote.total}</span> 元
            </span>
          ) : (
            <span className="text-sm text-muted-foreground">{quoting ? "在算价……" : catalog.methods.length || platform || phone ? "还没出价" : "这里还不能付款"}</span>
          )}
          {platform ? (
            <Button className="h-10 px-5" onClick={() => scrollToBlock("data-platforms")}>
              去平台下单
            </Button>
          ) : phone ? (
            <Button className="h-10 px-5" onClick={() => scrollToBlock("data-phone-pay")}>
              {phone.copyUrl ? "去微信里付" : "怎么付"}
            </Button>
          ) : (
            <Button className="h-10 px-6" disabled={!canPay} onClick={onPay}>
              {paying ? <Loader2 className="animate-spin" /> : null}
              去付款
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
