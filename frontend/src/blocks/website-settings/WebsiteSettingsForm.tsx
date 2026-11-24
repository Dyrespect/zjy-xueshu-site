import { Loader2 } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import type { ConsentRow, WebsiteConfigFull, WebsiteSettingsData } from "@/lib/website-types";
import { cn } from "@/lib/utils";

/**
 * 后台「官网」：页脚主体信息、联系电话、公安备案号、公开给搜索引擎、维护中。照发票设置那一页的排法（左边说明、右边输入）。
 * 空着的「正式开放前要补」项标「待填」。只吃 props。
 */

export interface WebsiteSettingsFormProps {
  data: WebsiteSettingsData;
  onSave: (config: WebsiteConfigFull) => Promise<void>;
}

const textCls = "h-9 w-full max-w-md rounded-md border border-input bg-background px-2.5 text-sm text-foreground outline-none focus-visible:border-ring";

function Row({ label, note, pending, children }: { label: string; note?: string; pending?: boolean; children: ReactNode }) {
  return (
    <div className="grid gap-2 border-t py-4 first:border-t-0 sm:grid-cols-[12rem_minmax(0,1fr)] sm:gap-6">
      <div className="flex flex-col gap-1">
        <span className="text-sm font-medium text-foreground">{label}</span>
        {pending ? <span className="w-fit rounded-full border border-foreground px-2 py-0.5 text-xs font-medium text-foreground">待填</span> : null}
      </div>
      <div className="flex flex-col gap-1.5">
        {children}
        {note ? <span className="text-xs leading-relaxed text-muted-foreground">{note}</span> : null}
      </div>
    </div>
  );
}

export function WebsiteSettingsForm({ data, onSave }: WebsiteSettingsFormProps) {
  const [c, setC] = useState<WebsiteConfigFull>(data.config);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const set = (patch: Partial<WebsiteConfigFull>) => setC({ ...c, ...patch });
  const pending = (k: keyof WebsiteConfigFull) => !String(c[k] ?? "").trim() && k in data.launch_fields;
  const text = (k: keyof WebsiteConfigFull, placeholder = "") => (
    <input
      id={`site-${k}`}
      className={textCls}
      value={String(c[k] ?? "")}
      placeholder={placeholder}
      onChange={(e) => set({ [k]: e.target.value } as Partial<WebsiteConfigFull>)}
    />
  );
  const toggle = (k: "indexable" | "maintenance", label: string) => (
    <label className="flex items-center gap-2 text-sm text-body">
      <input id={`site-${k}`} type="checkbox" checked={c[k]} onChange={(e) => set({ [k]: e.target.checked })} className="size-4 accent-primary" />
      {label}
    </label>
  );

  return (
    <div className="flex max-w-4xl flex-col">
      {data.pending_launch.length ? (
        <p className="mb-4 rounded-md border px-4 py-3 text-sm text-foreground">
          正式开放前还有 {data.pending_launch.length} 项待填：{data.pending_launch.map((k) => data.launch_fields[k]?.split("（")[0] ?? k).join("、")}。
        </p>
      ) : null}
      <h2 className="text-sm font-semibold text-foreground">页脚和关于我们</h2>
      <div className="mt-2">
        <Row label="公司全称">{text("company_name")}</Row>
        <Row label="统一社会信用代码">{text("credit_code")}</Row>
        <Row label="ICP 备案号" note="页脚链到工信部备案查询（beian.miit.gov.cn）。">{text("icp")}</Row>
        <Row label="公安联网备案号" pending={pending("police_beian")} note={data.launch_fields.police_beian}>
          {text("police_beian", "例：浙公网安备33010002000001号")}
        </Row>
        <Row label="联系电话">{text("phone")}</Row>
        <Row label="电话后面的说明">{text("phone_note", "例：微信同号")}</Row>
        <Row label="对外邮箱" pending={pending("email")} note={data.launch_fields.email}>{text("email", "例：kefu@example.com")}</Row>
        <Row label="公司地址" note="填了会显示在关于我们。">{text("address")}</Row>
        <Row label="客服时间" pending={pending("service_hours")} note={data.launch_fields.service_hours}>{text("service_hours", "例：每天 9:00–22:00")}</Row>
        <Row label="投诉答复时限" note="显示在联系我们、帮助中心（默认值是我们的建议，Edison 定）。">{text("reply_promise")}</Row>
      </div>
      <h2 className="mt-8 text-sm font-semibold text-foreground">营业执照公示（/license）</h2>
      <div className="mt-2">
        <Row label="类型" note="照营业执照填；执照变了十个工作日内改这里，执照图片换 frontend/public/site-assets/license.webp。">{text("license_type")}</Row>
        <Row label="法定代表人">{text("legal_rep")}</Row>
        <Row label="住所">{text("reg_address")}</Row>
        <Row label="成立日期">{text("established", "例：2026-06-09")}</Row>
        <Row label="登记机关">{text("registry_authority")}</Row>
      </div>
      <h2 className="mt-8 text-sm font-semibold text-foreground">去平台下单（自有网页暂不收款时）</h2>
      <div className="mt-2">
        <Row label="小红书店铺链接" note="微信支付、支付宝商户号没下来时，下单页「去付款」换成「现在请在小红书或闲鱼下单」。填了链接就能点过去，空着只显示文字。要 https:// 开头。">
          {text("xhs_shop_url", "https://…")}
        </Row>
        <Row label="闲鱼店铺链接">{text("xianyu_shop_url", "https://…")}</Row>
        <Row label="怎么找到店" note="选填，显示在两个平台下面。">{text("platform_shop_note", "例：两个平台都搜「心理学汇报 PPT 定制」")}</Row>
      </div>
      <h2 className="mt-8 text-sm font-semibold text-foreground">开关</h2>
      <div className="mt-2">
        <Row label="公开给搜索引擎" note="关着：robots.txt 全站不让爬，页面带 noindex。正式开放时打开；nginx 上那行 X-Robots-Tag 也要一起去掉（见部署说明）。">
          {toggle("indexable", "打开（允许百度、谷歌收录官网各页；交付页、付款页、后台始终不收录）")}
        </Row>
        <Row label="维护中" note="打开后官网各页和下单页显示「网站正在维护」；付款页、交付页、后台照常，避免影响已经付款、正在看稿的客人。">
          {toggle("maintenance", "打开")}
        </Row>
        <Row label="维护中的说明">{text("maintenance_text")}</Row>
      </div>
      <div className="mt-6 flex items-center gap-3">
        <Button
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            setMsg("");
            try {
              await onSave(c);
              setMsg("存好了，页脚和各页马上生效。");
            } catch (e) {
              setMsg(e instanceof Error ? e.message : "没存上");
            } finally {
              setBusy(false);
            }
          }}
        >
          {busy ? <Loader2 className="animate-spin" /> : null}
          保存
        </Button>
        {msg ? <span className={cn("text-sm", msg.startsWith("存好") ? "text-body" : "text-destructive")}>{msg}</span> : null}
      </div>
    </div>
  );
}

const ITEM_LABEL: Record<string, string> = { terms_privacy: "协议和隐私", ai_processing: "AI 和出境", custom_no_refund: "定制不退" };

/** 最近的「下单前同意」记录 */
export function ConsentLog({ rows }: { rows: ConsentRow[] }) {
  if (!rows.length) return <p className="text-sm text-muted-foreground">还没有记录。客人在下单页勾选建单、或在需求确认卡上勾选点「对，开工」后，这里会多一条。</p>;
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[40rem] border-collapse text-left text-sm">
        <thead>
          <tr className="text-xs text-muted-foreground">
            <th className="border-b py-2 pr-4 font-medium">时间</th>
            <th className="border-b py-2 pr-4 font-medium">挂在</th>
            <th className="border-b py-2 pr-4 font-medium">勾了</th>
            <th className="border-b py-2 pr-4 font-medium">协议 / 隐私版本</th>
            <th className="border-b py-2 pr-4 font-medium">IP</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i}>
              <td className="border-b py-2 pr-4 whitespace-nowrap tabular-nums">{new Date(r.at).toLocaleString("zh-CN", { hour12: false })}</td>
              <td className="border-b py-2 pr-4 font-mono text-xs">{r.checkout}</td>
              <td className="border-b py-2 pr-4">{r.items.map((x) => ITEM_LABEL[x] ?? x).join("、")}</td>
              <td className="border-b py-2 pr-4 tabular-nums">{r.terms_version} / {r.privacy_version}</td>
              <td className="border-b py-2 pr-4 tabular-nums">{r.ip}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
