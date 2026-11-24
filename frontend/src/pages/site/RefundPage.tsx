import { Link } from "react-router";

import { Container, NextLinks, Note, PageHead, Rows } from "@/blocks/site-section";

import { useCatalog } from "./catalog";
import { facts, REFUND_LEAD, refund } from "./content";

const a = "text-primary underline underline-offset-2 hover:text-primary-hover"; // 正文里的链接带下划线（不能只靠颜色区分，axe link-in-text-block）

/** 退款与售后：开工前可退，开工后先改；规则付款前就确认过。 */
export function RefundPage() {
  const { catalog } = useCatalog();
  const f = facts(catalog);
  return (
    <>
      <PageHead eyebrow="服务" title="退款与售后" lead={REFUND_LEAD} />
      <Container className="pb-12">
        <Rows className="max-w-[52rem]" items={refund(f).map((r) => ({ term: r.term, children: r.text }))} />
        <Note className="mt-6">
          以上规则在你下单前就写在
          <Link to="/price" className={a}>价目</Link>和<Link to="/service" className={a}>交付说明</Link>
          里，下单页付款前也会请你确认。撤单、售后和投诉找谁、多久答复，在<Link to="/contact" className={a}>联系我们</Link>。
        </Note>
      </Container>
      <NextLinks
        items={[
          { q: "多少钱", label: "价目", to: "/price" },
          { q: "你会拿到什么", label: "交付说明", to: "/service" },
        ]}
      />
    </>
  );
}
