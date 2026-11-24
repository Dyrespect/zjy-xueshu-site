import { Caption, Pic } from "@/blocks/site-home";
import { Container, ListNum, NextLinks, PageHead, Section, Steps } from "@/blocks/site-section";
import { MEDIA } from "@/lib/site-media";

import { useCatalog } from "./catalog";
import { facts, GET, how, notes } from "./content";

/**
 * 交付说明：你会拿到（5 条）→ 怎么交（3 步，配交付页真截图）→ 水印版长什么样（平台真出的水印样张）→ 注意事项。
 * 页头图：书桌上的显示器里是水印版（书桌是生成图，屏上的水印版是平台真出的）。轮数、天数、加购价从价目接口来。
 */
export function ServicePage() {
  const { catalog } = useCatalog();
  const f = facts(catalog);
  return (
    <>
      <PageHead
        eyebrow="服务"
        title="交付说明"
        lead="你拿到什么、怎么交、哪些不接，下单前都写在这。"
        media={
          <figure className="m-0">
            <Pic media={MEDIA.genB} priority sizes="(min-width: 1152px) 640px, (min-width: 768px) 56vw, 92vw" className="rounded-sm" />
            <Caption className="mt-3">示意：书桌是模型生成的，屏幕上是平台真出的一页水印版。</Caption>
          </figure>
        }
      />
      <Container>
        <Section title="你会拿到">
          <ListNum items={GET} />
        </Section>
        <Section title="怎么交">
          <Steps items={how(f)} />
          <figure className="m-0 max-w-3xl">
            <Pic
              media={MEDIA.r7Proof}
              slot="交付页截图：水印版一页 + 提修改框（R7）"
              ratio="16/10"
              sizes="(min-width: 1152px) 768px, 92vw"
              className="rounded-sm outline outline-1 -outline-offset-1 outline-border"
            />
            <Caption no="图 1" className="mt-3">
              交付页：水印版一页一页看，哪页要改就在哪页下面写；确认收货后这一页换成可编辑的 PPT 和讲稿下载。
            </Caption>
          </figure>
        </Section>
        <Section title="水印版长什么样" id="proof">
          <figure className="m-0 max-w-3xl">
            <Pic media={MEDIA.r5} slot="水印样张（R5，平台 watermark.py 真出的）" ratio="1920/1138" sizes="(min-width: 1152px) 768px, 92vw" className="rounded-sm shadow-figure outline outline-1 -outline-offset-1 outline-border" />
            <Caption no="图 2" className="mt-3">
              我们自己的一页，走一遍平台真的水印出图：整页完整大小，内容看得清，铺满斜纹水印、写着单号，底栏写第几版、第几页。客户收到的水印版就是这个样子。
            </Caption>
          </figure>
        </Section>
        <Section title="注意事项" id="notes">
          <ListNum items={notes(f)} />
        </Section>
      </Container>
      <NextLinks
        items={[
          { q: "做出来什么样", label: "样张", to: "/samples" },
          { q: "多少钱", label: "价目", to: "/price" },
          { q: "开工后能不能退", label: "退款与售后", to: "/refund" },
        ]}
      />
    </>
  );
}
