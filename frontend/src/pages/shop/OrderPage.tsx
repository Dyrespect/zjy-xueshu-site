import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";

import { CheckoutConsent } from "@/blocks/checkout-consent";
import { useCheckoutInvoice } from "@/blocks/invoice-form/load";
import { MaterialsGuide } from "@/blocks/materials-guide";
import { OrderPicker, type PhoneFallback, type PlatformShops } from "@/blocks/order-picker";
import { SiteFrame } from "@/blocks/site-shell/load";
import { usePageMeta } from "@/lib/page-meta";
import { createCheckout, getShopQuote, type OrderSelection, type ShopCatalog, type ShopQuote } from "@/lib/shop";
import { POLICY_VERSIONS, sitePage, siteTitle } from "@/lib/site-pages";
import { CONSENT_KEYS, getSiteConfig, type ConsentKey, type SiteConfig } from "@/lib/website";

import { loadCatalog } from "./site";

const NO_CONSENT: Record<ConsentKey, boolean> = { terms_privacy: false, ai_processing: false, custom_no_refund: false };

/** 复制到微信里打开用的下单页网址：带上选好的档位和来源 */
function orderLink(sel: OrderSelection, from: string | null): string {
  const q = new URLSearchParams({ tier: sel.tier, band: sel.band });
  if (from) q.set("from", from);
  return `${window.location.origin}/order?${q.toString()}`;
}

/** 页面上看得见的那一组勾选（宽屏在右栏、手机在底部，两处只显示一处） */
function scrollToConsent() {
  const el = [...document.querySelectorAll<HTMLElement>("[data-consent]")].find((x) => x.offsetParent !== null);
  el?.scrollIntoView({ behavior: "smooth", block: "center" });
}

/**
 * /order 下单页：价目从 /api/shop/catalog 来，每改一次选项问一次后端报价（/api/shop/quote），金额只认后端。
 * 付款前三项确认都勾上才建单：勾了什么、看的哪一版协议随单带给 /api/shop/checkout，后端交给节点 website.consent 校验并留痕，
 * 没勾全不建单（422）。自有网页暂不收款时（catalog.pay_mode = platforms，商户号没下来），照常看价选档，
 * 「去付款」换成去小红书 / 闲鱼下单（店铺链接在后台「官网」设置里，空着只显示文字）。
 * 手机上（docs/任务单/11_手机微信支付_设计.md）：微信里选「微信支付」→ 建单后整页跳去服务号网页授权（后端 /api/shop/wx/oauth），
 * 回来落在付款页再调起；手机浏览器没有能用的付款方式时，换成「复制网址到微信里打开」+ 去闲鱼下单。
 */
export function OrderPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [catalog, setCatalog] = useState<ShopCatalog | null>(null);
  const [loadError, setLoadError] = useState("");
  const [sel, setSel] = useState<OrderSelection>({
    tier: params.get("tier") || "regular",
    band: params.get("band") || "p1",
    rush: false,
    find_refs: false,
    extra_revisions: 0,
  });
  const [method, setMethod] = useState("");
  const [quote, setQuote] = useState<ShopQuote | null>(null);
  const [quoting, setQuoting] = useState(false);
  const [paying, setPaying] = useState(false);
  const [error, setError] = useState("");
  const seq = useRef(0);
  const invoice = useCheckoutInvoice(); // 下单页勾「需要发票」（开票模块，docs/任务单/07_开票_设计.md）
  const [consent, setConsent] = useState<Record<ConsentKey, boolean>>(NO_CONSENT);
  const [showMissing, setShowMissing] = useState(false);
  const [site, setSite] = useState<SiteConfig | null>(null);
  const page = sitePage("/order");
  usePageMeta(siteTitle(page?.title ?? "下单", "/order"), page?.description);

  useEffect(() => {
    loadCatalog(true)
      .then((c) => {
        setCatalog(c);
        setMethod(c.methods[0]?.method ?? "");
        setSel((s) => {
          const t = c.tiers.find((x) => x.key === s.tier) ?? c.tiers[0];
          const band = t?.prices[s.band] ? s.band : (c.bands.find((b) => t?.prices[b.key])?.key ?? s.band);
          return { ...s, tier: t?.key ?? s.tier, band };
        });
      })
      .catch((e) => setLoadError(e instanceof Error ? e.message : "打不开"));
    getSiteConfig().then(setSite, () => undefined); // 店铺链接取不到就只显示平台名字
    // 从微信授权页按返回、页面从缓存里恢复：按钮别卡在「处理中」
    const restored = (e: PageTransitionEvent) => e.persisted && setPaying(false);
    window.addEventListener("pageshow", restored);
    return () => window.removeEventListener("pageshow", restored);
  }, []);

  const platform: PlatformShops | undefined =
    catalog?.pay_mode === "platforms"
      ? {
          hint: catalog.hint || "现在请在小红书或闲鱼下单，付款后会收到兑换码",
          shops: [
            { label: "小红书", url: site?.xhs_shop_url ?? "" },
            { label: "闲鱼", url: site?.xianyu_shop_url ?? "" },
          ],
          note: site?.platform_shop_note ?? "",
        }
      : undefined;

  useEffect(() => {
    if (!catalog) return;
    const n = ++seq.current;
    setQuoting(true);
    setError("");
    const t = window.setTimeout(() => {
      getShopQuote(sel)
        .then((q) => n === seq.current && setQuote(q))
        .catch((e) => n === seq.current && setError(e instanceof Error ? e.message : "报不出价"))
        .finally(() => n === seq.current && setQuoting(false));
    }, 150);
    return () => window.clearTimeout(t);
  }, [catalog, sel]);

  // 手机上这里还不能直接付：复制网址（带上选好的档位）到微信里打开付，或者去闲鱼下单
  const phone: PhoneFallback | undefined =
    catalog && !platform && !catalog.methods.length && ["mobile", "wechat"].includes(catalog.ua_kind)
      ? {
          hint: catalog.hint,
          copyUrl: catalog.open_in_wechat ? orderLink(sel, params.get("from")) : undefined,
          xianyuUrl: site?.xianyu_shop_url ?? "",
        }
      : undefined;

  const pay = async () => {
    if (CONSENT_KEYS.some((k) => !consent[k])) {
      setShowMissing(true);
      scrollToConsent();
      return;
    }
    if (!(await invoice.beforePay())) return; // 勾了发票：先核对一遍
    setPaying(true);
    setError("");
    let leaving = false; // 整页跳走时按钮保持「处理中」，免得跳转那一下被再点一次、多建一张单
    try {
      const v = await createCheckout(sel, method, {
        session_ref: params.get("s") ?? "",
        source: params.get("from") ?? "",
        consents: CONSENT_KEYS.filter((k) => consent[k]),
        terms_version: POLICY_VERSIONS.terms,
        privacy_version: POLICY_VERSIONS.privacy,
      });
      const invoiceNote = await invoice.afterCheckout(v.view_token); // 存不上不挡付款
      if (v.pay.kind === "oauth" && typeof v.pay.payload.url === "string") {
        // 微信里付款：整页跳去服务号网页授权（静默，客人看不到弹框），回来直接落在付款页 /order/pay/:token 调起支付。
        // 用整页跳转而不是前端路由：调起支付的页面地址要是付款页本身（商户平台「支付授权目录」按它校验）
        leaving = true;
        window.location.assign(v.pay.payload.url);
        return;
      }
      navigate(`/order/pay/${v.view_token}`, invoiceNote ? { state: { invoiceNote } } : undefined);
    } catch (e) {
      setError(e instanceof Error ? e.message : "没下成单，再试一次");
    } finally {
      if (!leaving) setPaying(false);
    }
  };

  return (
    <SiteFrame current="/order" cta={false} className="text-base">
      {catalog ? (
        <OrderPicker
          catalog={catalog}
          selection={sel}
          onChange={setSel}
          quote={quote}
          quoting={quoting}
          method={method}
          onMethod={setMethod}
          onPay={pay}
          paying={paying}
          error={error}
          platform={platform}
          phone={phone}
          extra={platform || phone ? undefined : invoice.section}
          prepare={
            catalog.materials?.occasions.length ? (
              <details className="rounded-md border px-4 py-3" data-testid="order-materials">
                <summary className="cursor-pointer text-sm font-medium text-foreground">{catalog.materials.title}（按场合看要发哪几样）</summary>
                <div className="mt-4">
                  <MaterialsGuide guide={catalog.materials} compact />
                </div>
              </details>
            ) : undefined
          }
          consent={
            <CheckoutConsent
              checked={consent}
              onChange={(k, v) => setConsent((c) => ({ ...c, [k]: v }))}
              revisions={catalog.revisions_included}
              showMissing={showMissing}
            />
          }
        />
      ) : (
        <p className="mx-auto max-w-6xl px-4 py-16 text-sm text-muted-foreground sm:px-6">{loadError || "加载中……"}</p>
      )}
      {invoice.dialog}
    </SiteFrame>
  );
}
