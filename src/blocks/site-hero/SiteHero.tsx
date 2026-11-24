import type { ReactNode } from "react";

/**
 * 首页第一屏（官网v2方案.md H1）：产品即首屏（DJI、Apple 产品页；Linear 标题下接真界面）。
 * 上面一行：左边眉题 + 宋体大标题，右边一句定位、一段说明、两个按钮、起价一行；下面整宽放产品本身（看稿器，stage）。
 * 主张按「|」分段，每段不拆开（手机上断成「让汇报不再 / 卡在 PPT 上」）；不用 text-wrap: balance（Safari 会重排）。
 */

function keep(text: string) {
  return text.split("|").map((x, i) => (
    <span key={i} className="inline-block">
      {x}
    </span>
  ));
}

export interface HeroProps {
  /** 眉题（给谁、哪几种汇报） */
  eyebrow?: string;
  title: string;
  lead: string;
  text: string;
  actions: ReactNode;
  /** 起价那一句（价格从价目接口来） */
  meta?: ReactNode;
  /** 产品本身（看稿器） */
  stage?: ReactNode;
}

export function Hero({ eyebrow, title, lead, text, actions, meta, stage }: HeroProps) {
  return (
    <section aria-labelledby="hero-title" className="mx-auto max-w-6xl px-4 pt-10 pb-[clamp(4rem,3rem+4vw,7rem)] sm:px-6 sm:pt-16">
      <div className="grid gap-6 lg:grid-cols-[minmax(0,7fr)_minmax(0,5fr)] lg:items-end lg:gap-16">
        <div>
          {eyebrow ? <p className="text-[13px] font-medium tracking-[0.08em] text-muted-foreground">{eyebrow}</p> : null}
          <h1 id="hero-title" className="mt-4 font-headline text-display font-semibold tracking-[-0.01em] text-foreground">
            {keep(title)}
          </h1>
        </div>
        <div className="lg:pb-2">
          <p className="text-lead text-foreground">{keep(lead)}</p>
          <p className="mt-3 text-base leading-[1.8] text-body">{text}</p>
          <div className="mt-6 flex gap-3 [&>*]:flex-1 sm:[&>*]:flex-none">{actions}</div>
          {meta ? <p className="mt-4 text-sm text-muted-foreground">{meta}</p> : null}
        </div>
      </div>
      {stage ? <div className="mt-[clamp(2rem,1.5rem+2vw,3.5rem)]">{stage}</div> : null}
    </section>
  );
}
