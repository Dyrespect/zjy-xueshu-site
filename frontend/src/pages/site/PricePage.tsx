import { Link } from "react-router";

import { MaterialsGuide } from "@/blocks/materials-guide";
import { PriceTable } from "@/blocks/price-table";
import { Container, NextLinks, Note, PageHead, Rows, Section } from "@/blocks/site-section";
import { Button } from "@/components/ui/button";

import { useCatalog } from "./catalog";
import { addonText, facts } from "./content";

/** 价目：一张表说清（按时长选档、按篇数定价、含几轮修改），加购只有三样，最后是下单前要准备的资料（按场合）。
 * 数字和资料清单全从 /api/shop/catalog（sku.catalog）来。 */
export function PricePage() {
  const { catalog, error } = useCatalog();
  const f = facts(catalog);
  return (
    <>
      <PageHead
        eyebrow="服务"
        title="价目"
        lead={`按汇报时长选一档，再按材料篇数定价。价格是整份汇报的价格，含 ${f?.revisions ?? ""} 轮修改。`}
      />
      <Container className="pb-12">
        {catalog ? (
          <>
            <PriceTable tiers={catalog.tiers} bands={catalog.bands} />
            <Note className="mt-4">
              {catalog.page_rule_text}。时限从开工算，是交出水印版的时间，不含你看稿和改稿的时间。
            </Note>
            <div className="mt-6">
              <Button asChild size="lg" className="h-11 px-6">
                <Link to="/order">去下单</Link>
              </Button>
            </div>
          </>
        ) : (
          <Note>{error ? `价目没取到：${error}。刷新一下再试。` : "价目加载中……"}</Note>
        )}
      </Container>
      <Container>
        <Section title="加购">
          <Rows
            items={(catalog?.addons ?? [])
              .filter((a) => a.price)
              .map((a) => ({ term: a.name, meta: `+${a.price} 元`, children: addonText(a.key, f, a.note) }))}
          />
          <Note>所有价格单位为人民币元。价格以下单页显示为准。</Note>
        </Section>
        {catalog?.materials?.occasions.length ? (
          <Section title={catalog.materials.title} id="materials">
            <MaterialsGuide guide={catalog.materials} />
          </Section>
        ) : null}
      </Container>
      <NextLinks
        items={[
          { q: "你会拿到什么", label: "交付说明", to: "/service" },
          { q: "开工后能不能退", label: "退款与售后", to: "/refund" },
        ]}
      />
    </>
  );
}
