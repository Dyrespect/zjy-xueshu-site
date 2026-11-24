import { Link } from "react-router";

import { DraftNotice } from "@/blocks/legal-doc/DraftNotice";
import { Container, ListNum, Note, PageHead, Rows, Section, type RowItem } from "@/blocks/site-section";
import { useSiteConfig } from "@/blocks/site-shell/load";

const a = "text-primary underline underline-offset-2 hover:text-primary-hover"; // 正文里的链接带下划线（不能只靠颜色区分）

/**
 * 投诉与联系（电子商务法第五十九条：建立投诉举报机制、公开投诉举报方式）。草稿：答复时限是设置里的一句（我的建议「1 个工作日内」），
 * 个人信息请求 30 天内答复照 GB/T 35273—2020 第 8.7 条。外部途径只写全国 12315 平台。
 */
export function ContactPage() {
  const site = useSiteConfig();
  const channels: RowItem[] = site
    ? [
        {
          term: "电话、微信",
          children: (
            <>
              <a href={`tel:${site.phone}`} className="text-lg text-foreground tabular-nums hover:text-primary">{site.phone}</a>
              {site.phone_note ? `（${site.phone_note}，可添加）` : ""}
            </>
          ),
        },
        ...(site.email ? [{ term: "邮箱", children: <a href={`mailto:${site.email}`} className={a}>{site.email}</a> }] : []),
        ...(site.service_hours ? [{ term: "客服时间", children: site.service_hours }] : []),
        { term: "已下单的客户", children: "在交付页或接单助手中留言并注明单号，处理最快。" },
      ]
    : [];
  return (
    <>
      <PageHead eyebrow="关于" title="联系我们" lead="咨询、售后、投诉，以及个人信息的查阅、更正和删除，都可以通过以下方式联系我们。" />
      <Container>
        <div className="-mt-2 pb-6">
          <DraftNotice open={["投诉答复时限、客服时间和对外邮箱尚未最终确定。"]} />
        </div>
        <Section title="怎么联系我们">{site ? <Rows items={channels} /> : <Note>加载中……</Note>}</Section>
        <Section title="售后和投诉怎么处理" id="complaint">
          <ListNum
            items={[
              { lead: "告诉我们：", text: "你的单号或激活码、遇到了什么问题、希望怎么处理。有截图一起发。" },
              { lead: "我们答复：", text: `${site?.reply_promise ?? "收到后尽快答复"}；需要核实的，先告诉你大概多久有结果。` },
              { lead: "给出处理结果：", text: "按用户协议和退款与售后的规则处理：能改的先改，符合退款条件的原路退款。处理结果会告诉你理由。" },
              {
                lead: "还不满意：",
                text: (
                  <>
                    平台订单可以走平台的售后；也可以向消费者协会、市场监管部门投诉（
                    <a href="https://www.12315.cn/" target="_blank" rel="noopener noreferrer" className={a}>全国 12315 平台</a>
                    ），或者依法向人民法院起诉。
                  </>
                ),
              },
            ]}
          />
        </Section>
        <Section title="个人信息请求" id="privacy-requests">
          <Note className="text-base text-body">
            要查阅、复制、更正、删除你的个人信息，或者撤回同意，用上面的方式联系我们，说明单号或激活码（用来确认是你本人）。我们会在验证身份后三十天内答复，合理的请求不收费。详见
            <Link to="/privacy#rights" className={a}>隐私政策「你的权利」</Link>。
          </Note>
        </Section>
        <Section title="相关规则">
          <Note className="text-base text-body">
            <Link to="/refund" className={a}>退款与售后</Link>、<Link to="/terms" className={a}>用户协议</Link>、
            <Link to="/privacy" className={a}>隐私政策</Link>、<Link to="/disclaimer" className={a}>免责声明</Link>。
          </Note>
        </Section>
        <div className="pb-16" />
      </Container>
    </>
  );
}
