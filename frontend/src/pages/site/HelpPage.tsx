import { Link } from "react-router";

import { Caption, Pic } from "@/blocks/site-home";
import { Container, More, Note, PageHead, Section } from "@/blocks/site-section";
import { MEDIA } from "@/lib/site-media";

import { useCatalog } from "./catalog";
import { facts } from "./content";
import { helpGroups } from "./help";

const a = "text-primary underline underline-offset-2 hover:text-primary-hover"; // 正文里的链接带下划线（不能只靠颜色区分）

/** 帮助中心：常见问题按五组排，全部展开（好扫读、搜索引擎也看得到）；价格、时限从价目接口来。 */
export function HelpPage() {
  const { catalog } = useCatalog();
  const f = facts(catalog);
  const tiersLine = catalog ? catalog.tiers.map((t) => `${t.name} ${t.std_hours} 小时`).join("、") : "";
  const groups = helpGroups(f, tiersLine);
  return (
    <>
      <PageHead eyebrow="服务" title="帮助中心" lead="下单前后常见的问题。没有找到答案，可以在接单助手里问，或者通过「联系我们」页联系我们。" />
      <Container className="pb-16">
        <nav aria-label="问题分类" className="flex flex-wrap gap-x-6 gap-y-2 pb-8 text-sm">
          {groups.map((g) => (
            <a key={g.id} href={`#${g.id}`} className="text-body hover:text-foreground">
              {g.title}
            </a>
          ))}
        </nav>
        {groups.map((g) => (
          <Section key={g.id} id={g.id} title={g.title}>
            <dl className="flex max-w-2xl flex-col">
              {g.items.map((it) => (
                <div key={it.q} className="border-t py-5 first:border-t-0 first:pt-0">
                  <dt className="font-semibold text-foreground">{it.q}</dt>
                  <dd className="mt-2 leading-[1.8] text-body">
                    {it.a}
                    {it.more ? (
                      <>
                        {" "}
                        <Link to={it.more.to} className={`${a} whitespace-nowrap`}>
                          {it.more.label}
                        </Link>
                      </>
                    ) : null}
                    {it.shot ? (
                      <figure className="m-0 mt-4">
                        <Pic media={MEDIA[it.shot.key]} sizes="(min-width: 1152px) 672px, 92vw" className="rounded-sm outline outline-1 -outline-offset-1 outline-border" />
                        <Caption className="mt-2">{it.shot.caption}</Caption>
                      </figure>
                    ) : null}
                  </dd>
                </div>
              ))}
            </dl>
          </Section>
        ))}
        <Section title="还有问题">
          <Note className="text-base text-body">可以先看交付说明和价目；仍有疑问，请联系我们。</Note>
          <More to="/contact">联系我们</More>
        </Section>
      </Container>
    </>
  );
}
