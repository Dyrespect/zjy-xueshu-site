import { SiteLink } from "@/components/site-link";

export interface FooterLink {
  label: string;
  href: string;
}

export interface FooterGroup {
  key: string;
  title: string;
  items: FooterLink[];
}

export interface SiteFooterProps {
  /** 公司全称、统一社会信用代码、备案号（和官网同一套，来自后端站点地图） */
  company?: string;
  creditCode?: string;
  icp?: string;
  icpUrl?: string;
  /** 一句说明（版权、来源），可不填 */
  note?: string;
  /** 几组导航：汇报 PPT 定制 / 心理学科研图库 / 更多。官网、下单、兑换、图库的页全在这里连通 */
  groups?: FooterGroup[];
}

/** 官网、下单页、兑换页、图库共用的页脚（统一站点，模块 L）。 */
export function SiteFooter({ company, creditCode, icp, icpUrl = "https://beian.miit.gov.cn/", note, groups = [] }: SiteFooterProps) {
  return (
    <footer className="border-t bg-background">
      <div className="mx-auto flex max-w-6xl flex-col gap-8 px-4 py-8 text-sm sm:flex-row sm:justify-between sm:px-6">
        <div className="flex max-w-sm flex-col gap-1.5">
          {company ? <span className="font-medium text-foreground">{company}</span> : null}
          <p className="text-xs leading-relaxed text-muted-foreground">
            {creditCode ? (
              <>
                统一社会信用代码 {creditCode}
                <span aria-hidden className="mx-1.5">·</span>
                <SiteLink href="/license" className="underline underline-offset-2 hover:text-foreground">营业执照</SiteLink>
                <br />
              </>
            ) : null}
            {icp ? (
              <a href={icpUrl} target="_blank" rel="noopener noreferrer" className="hover:text-foreground">
                {icp}
              </a>
            ) : null}
          </p>
          {note ? <p className="text-xs leading-relaxed text-muted-foreground">{note}</p> : null}
        </div>
        {groups.length > 0 ? (
          <nav className="grid grid-cols-2 gap-x-10 gap-y-6 sm:grid-cols-3" aria-label="页脚导航">
            {groups.map((g) => (
              <div key={g.key} className="flex flex-col gap-2">
                <span className="text-xs font-medium text-foreground">{g.title}</span>
                {g.items.map((l) => (
                  <SiteLink key={l.href + l.label} href={l.href} className="text-muted-foreground hover:text-foreground">
                    {l.label}
                  </SiteLink>
                ))}
              </div>
            ))}
          </nav>
        ) : null}
      </div>
    </footer>
  );
}
