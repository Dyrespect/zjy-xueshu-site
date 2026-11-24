import { LegalDoc, type LegalDocData } from "@/blocks/legal-doc";
import { Note } from "@/blocks/site-section";
import { useSiteConfig } from "@/blocks/site-shell/load";
import type { SiteConfig } from "@/lib/website-types";

import { useCatalog } from "./catalog";

/** 协议正文里的占位符：公司名、电话这类来自官网设置，轮数、天数来自价目，不写死。 */
export function legalVars(site: SiteConfig, revisions: string, days: string): Record<string, string> {
  const phone = `电话 ${site.phone}${site.phone_note ? `（${site.phone_note}）` : ""}`;
  return {
    company: site.company_name,
    credit_code: site.credit_code,
    phone: site.phone,
    phone_note: site.phone_note,
    contact: site.email ? `${phone}或邮箱 ${site.email}` : phone,
    reply: site.reply_promise,
    revisions,
    days,
  };
}

/** 用户协议、隐私政策、免责声明（正文 Markdown 在 legal/，元信息在 legal/docs.ts）。设置没取到时先不画正文，免得露出 {phone} 这类占位符。 */
export function LegalPage({ doc }: { doc: LegalDocData }) {
  const site = useSiteConfig();
  const { catalog } = useCatalog();
  if (!site) return <Note className="mx-auto max-w-6xl px-4 py-16 sm:px-6">加载中……</Note>;
  const vars = legalVars(site, catalog ? String(catalog.revisions_included) : "约定", catalog ? String(catalog.auto_confirm_days) : "约定");
  return <LegalDoc doc={doc} vars={vars} />;
}
