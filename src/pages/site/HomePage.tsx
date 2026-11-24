import { ArrowRight } from "lucide-react";
import { Link } from "react-router";

import { Tiers } from "@/blocks/price-table";
import { Hero } from "@/blocks/site-hero";
import { Band, Caption, Compare, FlowChapter, keep, Pic, SampleRail, SlideViewer, Stat } from "@/blocks/site-home";
import { More, Note, Rows } from "@/blocks/site-section";
import { Button } from "@/components/ui/button";
import { MEDIA, type SiteMedia } from "@/lib/site-media";

import { useCatalog } from "./catalog";
import { BRIEF, CLOSING, COMPARE, FEEDBACK, FLOW, GALLERY, GOT, HERO, HOME_STEPS, homeGet, PRICE, REFUND_HOME, refund, SAMPLES, VIEWER, facts } from "./content";

const media = MEDIA as Record<string, SiteMedia>;

/**
 * 首页（官网v2方案.md 第二节）：卖什么（看稿器）→ 凭什么（原文对照）→ 样张 → 拿到什么 → 怎么交付 → 多少钱 → 谁说过 → 图库 → 退款 → 收尾。
 * 一屏一个焦点；全页只有样张那一条深色带。价格、页数、时限、轮数全从价目接口来，不手写。
 */
export function HomePage() {
  const { catalog } = useCatalog();
  const f = facts(catalog);
  const orderButtons = (
    <>
      <Button asChild size="lg" className="h-11 px-6">
        <Link to="/order">去下单</Link>
      </Button>
      <Button asChild size="lg" variant="outline" className="h-11 px-6">
        <Link to="/price">查看价目</Link>
      </Button>
    </>
  );
  return (
    <>
      <Hero
        eyebrow={HERO.eyebrow}
        title={HERO.title}
        lead={HERO.lead}
        text={HERO.text}
        actions={orderButtons}
        meta={
          f?.start ? (
            <>
              <span className="text-base font-semibold text-price tabular-nums">{f.start}</span> {HERO.meta}
            </>
          ) : null
        }
        stage={
          <SlideViewer
            slides={VIEWER.slides.map((s) => ({ media: MEDIA[s.key], label: s.label }))}
            caption={
              <>
                <span className="mr-2 font-medium text-foreground">{VIEWER.title}</span>
                {VIEWER.caption}
              </>
            }
          />
        }
      />

      {/* 01 原文到汇报页 */}
      <Band id="compare" no={COMPARE.no} eyebrow={COMPARE.eyebrow} title={keep(COMPARE.h)} lead={COMPARE.lead} className="pt-0 sm:pt-0">
        <div className="flex flex-col gap-[clamp(4rem,3rem+3vw,6rem)]">
          {COMPARE.groups.map((g) => (
            <Compare
              key={g.result}
              layout={g.layout}
              original={{ media: MEDIA[g.original], label: g.originalLabel, marks: [...g.marks] }}
              result={{ media: MEDIA[g.result], label: g.resultLabel }}
              no={g.no}
              caption={g.caption}
              source={g.source}
            />
          ))}
          <Stat n={COMPARE.stat.n} unit={COMPARE.stat.unit} text={COMPARE.stat.text} note={COMPARE.stat.note} />
        </div>
      </Band>

      {/* 02 样张（全页唯一的深色带） */}
      <Band
        id="samples"
        tone="inverse"
        no={SAMPLES.no}
        eyebrow={SAMPLES.eyebrow}
        title={keep(SAMPLES.h)}
        contained={false}
        aside={
          <Link to="/samples" className="group inline-flex items-center gap-1 font-medium text-inverse-foreground underline-offset-4 hover:underline">
            看全部样张
            <ArrowRight aria-hidden className="size-4 transition-transform group-hover:translate-x-0.5" />
          </Link>
        }
      >
        <SampleRail label="样张" items={SAMPLES.items.map((it) => ({ media: MEDIA[it.key], title: it.title, meta: it.meta }))} startNo={3} />
      </Band>

      {/* 03 你会拿到：左文右实拍 */}
      <Band id="get" no={GOT.no} eyebrow={GOT.eyebrow}>
        <div className="grid items-center gap-10 md:grid-cols-[minmax(0,5fr)_minmax(0,7fr)] md:gap-12 lg:gap-16">
          <div>
            <h2 className="font-headline text-headline font-semibold text-foreground">{GOT.h}</h2>
            <p className="mt-4 text-lead text-body">{GOT.lead}</p>
            <ul className="mt-8 flex flex-col">
              {homeGet(f).map((it) => (
                <li key={it.title} className="border-t py-4">
                  <div className="font-semibold text-foreground">{it.title}</div>
                  <p className="mt-1 text-sm leading-relaxed text-body">{it.text}</p>
                </li>
              ))}
            </ul>
            <div className="mt-2">
              <More to="/service">完整交付说明</More>
            </div>
          </div>
          <figure className="m-0">
            <Pic media={MEDIA.yiSet} sizes="(min-width: 1152px) 640px, (min-width: 768px) 56vw, 92vw" className="rounded-sm outline outline-1 -outline-offset-1 outline-border" />
            <Caption className="mt-4">{GOT.caption}</Caption>
          </figure>
        </div>
      </Band>

      {/* 04 怎么交付：粘性章节 */}
      <Band id="flow" no={FLOW.no} eyebrow={FLOW.eyebrow} title={keep(FLOW.h)} tone="card">
        {/* 付款后的需求引导：一小段，不做大模块（需求卡页面做好后右边换真截图） */}
        <div className="mb-[clamp(3rem,2rem+3vw,5rem)] grid items-center gap-6 border-y py-8 md:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] md:gap-12">
          <div>
            <h3 className="text-lg font-semibold text-foreground">{BRIEF.h}</h3>
            <ol className="mt-4 flex flex-wrap gap-x-8 gap-y-2">
              {BRIEF.steps.map((t, i) => (
                <li key={t} className="flex items-baseline gap-2 text-body">
                  <span className="text-sm text-muted-foreground tabular-nums">{i + 1}</span>
                  {t}
                </li>
              ))}
            </ol>
            <p className="mt-4 leading-[1.8] text-body">{BRIEF.after}</p>
          </div>
          <Pic slot={BRIEF.slot} ratio="16/10" />
        </div>
        <FlowChapter
          steps={HOME_STEPS.map((s, i) => ({ title: s.title, text: s.text, media: media[FLOW.shots[i].key], slot: FLOW.shots[i].slot }))}
        />
        <div className="mt-10">
          <More to="/service#notes">下单前看注意事项</More>
        </div>
      </Band>

      {/* 05 价目 */}
      <Band
        id="price"
        no={PRICE.no}
        eyebrow={PRICE.eyebrow}
        title={
          f?.start ? (
            <>
              <span className="tabular-nums">{f.start}</span> {keep(PRICE.h)}
            </>
          ) : (
            keep(PRICE.h.replace(/^元起，\|?/, ""))
          )
        }
      >
        {catalog ? <Tiers tiers={catalog.tiers} /> : <Note>价目加载中……</Note>}
        <div className="mt-10 flex flex-col gap-6 md:flex-row md:items-baseline md:justify-between">
          <Note>
            价格是整份汇报的价格，含 {f?.revisions ?? ""} 轮修改。{catalog?.bands.slice(1).map((b) => b.name).join("、")}材料另有价格。
          </Note>
          <More to="/price">完整价目和加购</More>
        </div>
      </Band>

      {/* 06 用过的人怎么说：真截图 + 一行身份，不做证言卡 */}
      <Band id="feedback" no={FEEDBACK.no} eyebrow={FEEDBACK.eyebrow} title={keep(FEEDBACK.h)} tone="card">
        {/* 截图按原比例放，不拉伸、不留大空：最长那张（逐句说清楚的）在左，另两张叠在右边 */}
        <ul className="grid items-start gap-6 md:grid-cols-12">
          {FEEDBACK.items.map((it, i) => (
            <li key={it.key} className={i === 1 ? "md:col-span-7 md:row-span-2 md:row-start-1" : "md:col-span-5"}>
              <figure className="m-0">
                <div className="rounded-sm bg-background p-5 outline outline-1 -outline-offset-1 outline-border">
                  <Pic media={media[it.key]} sizes={i === 1 ? "(min-width: 1152px) 620px, (min-width: 768px) 56vw, 92vw" : "(min-width: 1152px) 420px, (min-width: 768px) 38vw, 92vw"} />
                </div>
                <Caption className="mt-3">{it.who}</Caption>
              </figure>
            </li>
          ))}
        </ul>
        <Note className="mt-6">{FEEDBACK.note}</Note>
      </Band>

      {/* 07 科研图库入口：只放有设计的期刊图（试次流程、研究总览、理论框架……），卡片放大到能看清构图 */}
      <Band
        id="gallery"
        no={GALLERY.no}
        eyebrow={GALLERY.eyebrow}
        title={keep(GALLERY.h)}
        lead={GALLERY.lead}
        aside={<More to="/tuku">去科研图库</More>}
      >
        <ul className="grid gap-x-6 gap-y-8 sm:grid-cols-2 lg:grid-cols-3">
          {GALLERY.items.map((it) => (
            <li key={it.key}>
              <figure className="m-0">
                <div className="flex aspect-[4/3] items-center justify-center overflow-hidden rounded-sm bg-background p-3 outline outline-1 -outline-offset-1 outline-border">
                  <Pic media={media[it.key]} sizes="(min-width: 1024px) 360px, (min-width: 640px) 45vw, 92vw" className="max-h-full w-auto object-contain" />
                </div>
                <Caption className="mt-3">
                  <span className="font-medium text-foreground">{it.kind}</span>
                  <span aria-hidden className="mx-1.5">·</span>
                  {it.journal}
                </Caption>
              </figure>
            </li>
          ))}
        </ul>
        <Note className="mt-8">{GALLERY.note}</Note>
      </Band>

      {/* 08 退款与售后 */}
      <Band id="refund" no={REFUND_HOME.no} eyebrow={REFUND_HOME.eyebrow} title={REFUND_HOME.h} className="pt-0 sm:pt-0">
        <Rows items={refund(f).slice(0, 3).map((r) => ({ term: r.term, children: r.text }))} className="max-w-4xl" />
        <div className="mt-8">
          <More to="/refund">退款与售后全文</More>
        </div>
      </Band>

      {/* 收尾：上台那天 */}
      <section aria-labelledby="closing-title" className="border-t">
        <div className="mx-auto max-w-6xl px-4 py-[clamp(4rem,3rem+4vw,7rem)] sm:px-6">
          <div className="flex flex-col gap-6 md:flex-row md:items-end md:justify-between">
            <h2 id="closing-title" className="font-headline text-headline font-semibold text-foreground">
              {keep(CLOSING.h)}
            </h2>
            <div className="flex gap-3 [&>*]:flex-1 sm:[&>*]:flex-none">{orderButtons}</div>
          </div>
          <figure className="m-0 mt-[clamp(2rem,1.5rem+2vw,3.5rem)]">
            <Pic media={MEDIA.genA} slot="空研讨室投影幕上是我们的真页（GEN-A + P09）" ratio="16/7" sizes="(min-width: 1152px) 1104px, 92vw" className="rounded-sm" />
            <Caption className="mt-4 max-w-3xl">{CLOSING.caption}</Caption>
          </figure>
        </div>
      </section>
    </>
  );
}
