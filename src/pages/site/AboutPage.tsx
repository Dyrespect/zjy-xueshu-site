import { Link } from "react-router";

import { Caption, Pic } from "@/blocks/site-home";
import { Container, More, PageHead, Prose, Rows, Section, type RowItem } from "@/blocks/site-section";
import { useSiteConfig } from "@/blocks/site-shell/load";
import { MEDIA, MEDIA_BASE } from "@/lib/site-media";

const a = "text-primary underline underline-offset-2 hover:text-primary-hover"; // 正文里的链接带下划线（不能只靠颜色区分）

/** 关于我们：谁在做这件事（主体信息、备案信息），怎么联系。全部来自官网设置。 */
export function AboutPage() {
  const site = useSiteConfig();
  const facts: RowItem[] = site
    ? [
        { term: "公司名称", children: site.company_name },
        { term: "统一社会信用代码", children: <span className="tabular-nums">{site.credit_code}</span> },
        ...(site.address ? [{ term: "地址", children: site.address }] : []),
        {
          term: "网站备案",
          children: (
            <a href={site.icp_url} target="_blank" rel="noopener noreferrer" className={a}>
              {site.icp}
            </a>
          ),
        },
        ...(site.police_beian
          ? [{ term: "公安备案", children: <a href={site.police_beian_url} target="_blank" rel="noopener noreferrer" className={a}>{site.police_beian}</a> }]
          : []),
      ]
    : [];
  const contact: RowItem[] = site
    ? [
        {
          term: "电话",
          children: (
            <>
              <a href={`tel:${site.phone}`} className="text-lg text-foreground tabular-nums hover:text-primary">{site.phone}</a>
              {site.phone_note ? `（${site.phone_note}，可添加）` : ""}
            </>
          ),
        },
        ...(site.email ? [{ term: "邮箱", children: <a href={`mailto:${site.email}`} className={a}>{site.email}</a> }] : []),
        ...(site.service_hours ? [{ term: "客服时间", children: site.service_hours }] : []),
      ]
    : [];
  return (
    <>
      <PageHead
        eyebrow="关于"
        title="关于我们"
        lead={`${site?.company_name ?? ""}，为心理学研究生和博士生提供汇报 PPT 定制服务：组会文献汇报、开题、中期、答辩、会议报告。`}
      />
      <Container className="pb-16">
        <Section title="我们怎么做">
          {/* 竹涧云横版字标：单色剪影跟着字色走（标志定稿是深绿，和 PPT 这条线的蓝不是一套，只用形状） */}
          <span
            role="img"
            aria-label={site?.company_name ?? "竹涧云"}
            className="block h-12 w-[7rem] bg-foreground"
            style={{ WebkitMask: `url(${MEDIA_BASE}/l01-600.webp) left center / contain no-repeat`, mask: `url(${MEDIA_BASE}/l01-600.webp) left center / contain no-repeat` }}
          />
          <Prose>
            <p>你发来论文或材料，我们按你的汇报时长做成可编辑的 PPT 和逐页讲稿。内容只用你的材料和原文，每条标出处；原文没画、光靠文字讲不清的，按心理学好刊的画法画出来。</p>
            <p>
              我们用 AI 辅助制作，经审读、检查后交付；先交水印版供你确认，确认收货后再发可编辑的文件。详见
              <Link to="/service" className={a}>交付说明</Link>和<Link to="/disclaimer" className={a}>免责声明</Link>。
            </p>
          </Prose>
          <figure className="m-0 max-w-3xl">
            <Pic media={MEDIA.n09} sizes="(min-width: 1152px) 768px, 92vw" className="rounded-sm shadow-figure outline outline-1 -outline-offset-1 outline-border" />
            <Caption no="图 1" className="mt-3" source="组会文献汇报第 38 页，讲 Cheng et al. (2022)。">
              原文分几段写的信号处理，我们画成六步流水线，每步一个示意波形，没做过超扫描的同学也看得懂脑间同步是怎么算出来的。
            </Caption>
          </figure>
        </Section>
        <Section title="谁在做">
          <Pic slot="「谁在做」：像素形象 L05、真人照片，或者不放（等 Edison 定）" ratio="4/1" className="max-w-3xl" />
          <Prose>
            <p>我们也在公众号 PsyEngine 每天讲一篇心理学论文，配一份免费的汇报 PPT。</p>
          </Prose>
          <figure className="m-0 flex items-center gap-4">
            <Pic media={MEDIA.l07} sizes="112px" className="size-28 shrink-0 rounded-sm outline outline-1 -outline-offset-1 outline-border" />
            <Caption>微信扫码关注公众号 PsyEngine：每天一篇论文解读和一份免费 PPT。</Caption>
          </figure>
        </Section>
        <Section title="主体信息">{site ? <Rows items={facts} /> : null}</Section>
        <Section title="联系我们">
          {site ? <Rows items={contact} /> : null}
          <More to="/contact">售后、投诉和个人信息请求</More>
        </Section>
      </Container>
    </>
  );
}
