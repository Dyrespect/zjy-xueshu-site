import { Loader2 } from "lucide-react";
import { useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import type { EntryAdmin, EntryConfig } from "@/lib/entry-types";

export interface EntrySettingsProps {
  data: EntryAdmin;
  onSave: (body: { config?: EntryConfig; checklists?: Record<string, unknown> }) => Promise<void>;
  onMakeLink: () => Promise<void>;
}

const numCls = "h-9 w-24 rounded-md border border-input bg-background px-2.5 text-sm text-foreground outline-none focus-visible:border-ring";
const areaCls = "min-h-72 w-full max-w-3xl rounded-md border border-input bg-background px-3 py-2 font-mono text-xs leading-relaxed text-foreground outline-none focus-visible:border-ring";
const CRED_LABELS: Record<string, string> = { corpid: "企业 ID", secret: "客服 Secret", token: "回调 Token", aes_key: "EncodingAESKey", open_kfid: "客服账号 ID" };

function Row({ label, note, children }: { label: string; note?: string; children: ReactNode }) {
  return (
    <div className="grid gap-2 border-t py-4 first:border-t-0 sm:grid-cols-[12rem_minmax(0,1fr)] sm:gap-6">
      <div className="flex flex-col gap-1">
        <span className="text-sm font-medium text-foreground">{label}</span>
        {note ? <span className="text-xs leading-relaxed text-muted-foreground">{note}</span> : null}
      </div>
      <div className="flex min-w-0 flex-col gap-2">{children}</div>
    </div>
  );
}

/** 后台「入口」页：微信客服（开关、凭证配了没有、兑换用的客服链接）、限额、邮件服务、资料清单。只吃 props。 */
export function EntrySettings({ data, onSave, onMakeLink }: EntrySettingsProps) {
  const [cfg, setCfg] = useState<EntryConfig>(data.config);
  const [checklists, setChecklists] = useState(JSON.stringify(data.checklists, null, 2));
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const up = (p: Partial<EntryConfig>) => setCfg((c) => ({ ...c, ...p }));
  const run = (what: string, p: Promise<void>) => {
    setBusy(what);
    setError("");
    void p.catch((e) => setError(e instanceof Error ? e.message : "没存上")).finally(() => setBusy(""));
  };
  const link = data.config.wecom_links.redeem ?? "";
  return (
    <div className="flex flex-col gap-8">
      <section className="flex flex-col">
        <h2 className="mb-2 text-base font-semibold text-foreground">登录</h2>
        <Row label="认领前要求登录" note="默认开：兑换页第一步登录（微信里自动、电脑扫码、手机号），订单记在账号下。这台设备一种登录方式都没开时照旧不登录认领；微信登录哪天出了问题，在这里关掉 = 所有设备都不登录也能认领。">
          <label className="flex items-center gap-2 text-sm text-body">
            <input type="checkbox" checked={cfg.login_required ?? true} onChange={(e) => up({ login_required: e.target.checked })} />
            认领前先登录
          </label>
        </Row>
      </section>
      <section className="flex flex-col">
        <h2 className="mb-2 text-base font-semibold text-foreground">微信客服</h2>
        <Row label="开关" note="默认关。企业认证、回调域名、凭证配好，生成了兑换用的客服链接以后再打开；关着时兑换页不出「用微信客服继续」，也不发微信消息。">
          <label className="flex items-center gap-2 text-sm text-body">
            <input type="checkbox" checked={cfg.wecom_enabled} onChange={(e) => up({ wecom_enabled: e.target.checked })} />
            打开微信客服
          </label>
          <span className="text-xs text-muted-foreground" data-testid="wecom-state">
            {data.wecom.available ? "现在能用" : `现在不能用：${data.wecom.reason}`}
          </span>
        </Row>
        <Row label="凭证" note="在服务器的 .env 里填（这里只显示配了没有，不显示值）。">
          <ul className="flex flex-wrap gap-x-4 gap-y-1 text-sm">
            {Object.entries(data.wecom.configured).map(([k, v]) => (
              <li key={k} className={v ? "text-body" : "text-muted-foreground"}>
                {CRED_LABELS[k] ?? k}：{v ? "配了" : "没配"}
              </li>
            ))}
          </ul>
          <span className="text-xs text-muted-foreground">回调地址：https://你的域名{data.wecom.callback_path}</span>
        </Row>
        <Row label="兑换用的客服链接" note="上线时点一次：调企业微信生成一条 scene=redeem 的客服链接，兑换页在末尾拼上激活码。">
          {link ? <code className="break-all text-xs text-body">{link}</code> : <span className="text-sm text-muted-foreground">还没生成</span>}
          <Button variant="outline" size="sm" className="w-fit" disabled={!!busy || !data.wecom.client_ready} onClick={() => run("link", onMakeLink())}>
            {busy === "link" ? <Loader2 className="animate-spin" /> : null}
            {link ? "重新生成" : "生成兑换用的客服链接"}
          </Button>
        </Row>
        <Row label="给交付留几条" note="客人说话后 48 小时最多发 5 条；这单在制作中、窗口只剩这么几条时，只发交付类的话。">
          <input type="number" min={0} max={4} className={numCls} value={cfg.wecom_reserve_for_delivery}
            onChange={(e) => up({ wecom_reserve_for_delivery: Number(e.target.value) })} />
        </Row>
      </section>

      <section className="flex flex-col">
        <h2 className="mb-2 text-base font-semibold text-foreground">限额和其他</h2>
        <Row label="访客每天条数" note="没认领的会话每人、全站每天助手回几条：在「设置」页改。">
          <span className="text-sm text-body">每人 {data.visitor.daily} 条，全站 {data.visitor.global_daily} 条</span>
        </Row>
        <Row label="网页同一 IP 每天" note="没认领时同一 IP 一天最多问几条（换会话也算）。">
          <input type="number" min={1} className={numCls} value={cfg.web_visitor_ip_daily}
            onChange={(e) => up({ web_visitor_ip_daily: Number(e.target.value) })} />
        </Row>
        <Row label="兑换页同一 IP 每小时" note="防撞库：查码超过这个数回「查得太频繁」。">
          <input type="number" min={1} className={numCls} value={cfg.redeem_ip_hourly}
            onChange={(e) => up({ redeem_ip_hourly: Number(e.target.value) })} />
        </Row>
        <Row label="邮件服务" note="配了才有「我的订单」（凭订单号 + 邮箱查）；在 .env 的 EMAIL_* 里配。">
          <span className="text-sm text-body">{data.email.enabled ? `开着（${data.email.via}）` : "没配：「我的订单」整块关闭"}</span>
        </Row>
        <div className="pt-2">
          <Button disabled={!!busy} onClick={() => run("cfg", onSave({ config: cfg }))}>
            {busy === "cfg" ? <Loader2 className="animate-spin" /> : null}
            保存微信客服和限额
          </Button>
        </div>
      </section>

      <section className="flex flex-col gap-3">
        <div>
          <h2 className="text-base font-semibold text-foreground">资料清单</h2>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
            认领以后按这张清单收资料：default 是默认一张；addons 是加购替换哪几项（帮我找文献：主材料换成方向和关键词）；overrides 按货号覆盖。
            主材料要哪种看场合（设置页的场合表），份数看篇数档。
          </p>
        </div>
        <textarea aria-label="资料清单" className={areaCls} value={checklists} onChange={(e) => setChecklists(e.target.value)} spellCheck={false} />
        <Button
          variant="outline"
          className="w-fit"
          disabled={!!busy}
          onClick={() => {
            let parsed: Record<string, unknown>;
            try {
              parsed = JSON.parse(checklists) as Record<string, unknown>;
            } catch {
              setError("资料清单不是合法的 JSON");
              return;
            }
            run("cl", onSave({ checklists: parsed }));
          }}
        >
          {busy === "cl" ? <Loader2 className="animate-spin" /> : null}
          保存资料清单
        </Button>
      </section>
      {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
    </div>
  );
}
