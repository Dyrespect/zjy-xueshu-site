import { Link } from "react-router";

import { Container, PageHead, Section } from "@/blocks/site-section";
import { SITE_GROUPS, SITE_PAGES } from "@/lib/site-pages";

/** 网站地图：本站所有对外页面，按页脚的三组排（清单在 lib/site-pages.ts，和页脚、sitemap.xml 同一份）。 */
export function SitemapPage() {
  return (
    <>
      <PageHead eyebrow="关于" title="网站地图" lead="本站所有对外的页面。" />
      <Container className="pb-16">
        {SITE_GROUPS.map((g) => (
          <Section key={g} title={g}>
            <ul className="flex flex-col">
              {SITE_PAGES.filter((p) => p.group === g).map((p) => (
                <li key={p.path} className="border-t py-4 first:border-t-0 first:pt-0">
                  <Link to={p.path} className="font-medium text-primary hover:text-primary-hover">
                    {p.title}
                  </Link>
                  <p className="mt-1 max-w-2xl text-sm leading-relaxed text-body">{p.description}</p>
                </li>
              ))}
            </ul>
          </Section>
        ))}
      </Container>
    </>
  );
}
