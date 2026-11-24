import { Check, Circle, Loader2, Plus, X } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import type { Addon, AdminSettings, BizConfig, DurationTier } from "@/lib/admin-types";
import { cn } from "@/lib/utils";

import { MaterialsEditor } from "./MaterialsEditor";

export interface SettingsFormProps {
  settings: AdminSettings;
  onSave: (config: BizConfig) => Promise<void>;
  onContactWay: (scene: string) => Promise<string>;
  /** 图片预览地址：付款二维码、负责人微信二维码、客服二维码 */
  imageUrl?: (name: "pay_qr" | "owner_qr" | "service_qr") => string;
}

const numCls = "h-8 w-20 rounded-md border border-input bg-background px-2.5 text-sm text-foreground outline-none focus-visible:border-ring";
const textCls = "h-8 w-full min-w-0 rounded-md border border-input bg-background px-2.5 text-sm text-foreground outline-none focus-visible:border-ring";
const areaCls =
  "field-sizing-content min-h-24 w-full max-w-2xl rounded-md border border-input bg-background px-3 py-2 text-sm leading-relaxed text-foreground outline-none focus-visible:border-ring";

function Block({ title, children, note }: { title: string; children: ReactNode; note?: ReactNode }) {
  return (
    <section className="border-t py-6 first:border-t-0 first:pt-0">
      <h2 className="text-base font-semibold text-foreground">{title}</h2>
      {note ? <p className="mt-1 max-w-2xl text-sm text-body">{note}</p> : null}
      <div className="mt-4">{children}</div>
    </section>
  );
}

function Status({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-sm">
      {ok ? <Check className="size-4 text-primary" /> : <Circle className="size-4 text-faint" />}
      <span className={ok ? "text-foreground" : "text-body"}>{label}</span>
    </span>
  );
}

const CONFIRM_SOURCES: { key: string; label: string }[] = [
  { key: "customer", label: "客人点确认收货" },
  { key: "auto", label: "超时自动确认" },
  { key: "platform", label: "平台信号" },
  { key: "edison", label: "你在后台点" },
];
const PLATFORM_LABEL: Record<string, string> = {
  web: "自有网页", fk: "发卡站", manual: "手动开单", legacy: "旧数据", xhs: "小红书", xy: "闲鱼", dy: "抖音",
};

function Tbd() {
  return <span className="ml-1.5 text-xs text-price">待定</span>;
}

/** 后台设置：价目（时长档 × 篇数档）、加购、排期、访客上限、确认收货、场合表、交付什么和注意事项、付款渠道、发货内容、
 * 哪几类先给你看、欢迎语和问答卡、图片、企业微信。 */
export function SettingsForm({ settings, onSave, onContactWay, imageUrl }: SettingsFormProps) {
  const [cfg, setCfg] = useState<BizConfig>(settings.config);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState("");
  const [scene, setScene] = useState("gzh_article");
  const [link, setLink] = useState("");
  const [linkErr, setLinkErr] = useState("");
  useEffect(() => setCfg(settings.config), [settings]);
  const dirty = useMemo(() => JSON.stringify(cfg) !== JSON.stringify(settings.config), [cfg, settings.config]);
  const w = settings.wecom;
  const wecomReady = w.corpid && w.secret && w.open_kfid;

  const up = (patch: Partial<BizConfig>) => setCfg((c) => ({ ...c, ...patch }));
  const upTier = (i: number, patch: Partial<DurationTier>) =>
    setCfg((c) => ({ ...c, duration_tiers: c.duration_tiers.map((t, j) => (j === i ? { ...t, ...patch } : t)) }));
  const upAddon = (i: number, patch: Partial<Addon>) => setCfg((c) => ({ ...c, addons: c.addons.map((a, j) => (j === i ? { ...a, ...patch } : a)) }));
  const toggleSource = (platform: string, source: string, on: boolean) =>
    setCfg((c) => {
      const cur = c.delivery.confirm_sources_by_platform[platform] ?? [];
      const next = on ? [...cur.filter((x) => x !== source), source] : cur.filter((x) => x !== source);
      return { ...c, delivery: { ...c.delivery, confirm_sources_by_platform: { ...c.delivery.confirm_sources_by_platform, [platform]: next } } };
    });

  async function save() {
    setBusy(true);
    setSaved("");
    try {
      await onSave(cfg);
      setSaved("存好了");
    } catch (e) {
      setSaved(e instanceof Error ? e.message : "没存上");
    } finally {
      setBusy(false);
    }
  }

  const paymentReady = !!cfg.payment.link.trim() || (!!cfg.payment.qr_image.trim() && settings.images.pay_qr);

  return (
    <div className="pb-24">
      <Block
        title="价目：时长档 × 篇数"
        note="Edison 11-18 定的现价。档名写上限，客户报的时长超了就升一档；价格空着 = 这一格不开放；页数按内容页算。「以后压到」只是备注，不参与报价（专用号到位、月单量稳定 60 单以上再压）。"
      >
        <div className="overflow-x-auto">
          <table className="w-full min-w-[860px] text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground">
                <th className="py-2 pr-3 font-normal">档</th>
                <th className="py-2 pr-3 font-normal">时长上限（分钟）</th>
                <th className="py-2 pr-3 font-normal">页数上限</th>
                {cfg.paper_bands.map((b) => (
                  <th key={b.key} className="py-2 pr-3 font-normal">
                    {b.name}（元）
                  </th>
                ))}
                <th className="py-2 pr-3 font-normal">标准（小时）</th>
                <th className="py-2 pr-3 font-normal">加急（小时）</th>
                <th className="py-2 pr-3 font-normal">开加急</th>
                <th className="py-2 font-normal">以后压到</th>
              </tr>
            </thead>
            <tbody>
              {cfg.duration_tiers.map((t, i) => (
                <tr key={t.key} className="border-t align-middle">
                  <td className="py-2.5 pr-3">
                    <input className={cn(textCls, "w-16")} aria-label="档名" value={t.name} onChange={(e) => upTier(i, { name: e.target.value })} />
                  </td>
                  <td className="py-2.5 pr-3">
                    <input type="number" min={1} className={numCls} aria-label={`${t.name}的时长上限`} value={t.max_minutes} onChange={(e) => upTier(i, { max_minutes: Number(e.target.value) })} />
                  </td>
                  <td className="py-2.5 pr-3">
                    <input type="number" min={1} className={numCls} aria-label={`${t.name}的页数上限`} value={t.max_pages} onChange={(e) => upTier(i, { max_pages: Number(e.target.value) })} />
                  </td>
                  {cfg.paper_bands.map((b) => (
                    <td key={b.key} className="py-2.5 pr-3">
                      <input
                        className={cn(textCls, "w-20")}
                        aria-label={`${t.name}${b.name}的价格`}
                        placeholder="不开放"
                        value={t.prices[b.key] ?? ""}
                        onChange={(e) => upTier(i, { prices: { ...t.prices, [b.key]: e.target.value } })}
                      />
                    </td>
                  ))}
                  <td className="py-2.5 pr-3">
                    <input type="number" min={1} className={numCls} aria-label={`${t.name}的标准时限`} value={t.std_hours} onChange={(e) => upTier(i, { std_hours: Number(e.target.value) })} />
                  </td>
                  <td className="py-2.5 pr-3">
                    <input type="number" min={1} className={numCls} aria-label={`${t.name}的加急时限`} value={t.rush_hours} onChange={(e) => upTier(i, { rush_hours: Number(e.target.value) })} />
                  </td>
                  <td className="py-2.5 pr-3">
                    <input type="checkbox" className="accent-primary" aria-label={`${t.name}开放加急`} checked={t.rush} onChange={(e) => upTier(i, { rush: e.target.checked })} />
                  </td>
                  <td className="py-2.5">
                    <input className={cn(textCls, "w-20")} aria-label={`${t.name}以后压到`} placeholder="—" value={t.later_price} onChange={(e) => upTier(i, { later_price: e.target.value })} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 max-w-2xl text-xs text-muted-foreground">
          标准、加急填的是正常用时（开工起，不含排队和客户来回）；对客人说的时限再加下面的余量。不加急的单，第一版不早于加急的承诺时间发。
        </p>
        <label className="mt-4 flex max-w-2xl flex-col gap-1.5">
          <span className="text-sm text-foreground">页数怎么算（报价、开单说明里照这句说）</span>
          <input className={textCls} aria-label="页数怎么算" value={cfg.page_rule_text} onChange={(e) => up({ page_rule_text: e.target.value })} />
        </label>
      </Block>

      <Block title="加购" note="加急只对开了加急的档、材料齐的单，限名额；做不到按标准做、给你记一条退加急费。帮我找文献不开放加急。价格空着 = 不卖。">
        <div className="flex max-w-3xl flex-col gap-2">
          {cfg.addons.map((a, i) => (
            <div key={a.key} className="grid grid-cols-[6rem_6rem_1fr] items-center gap-2">
              <input className={textCls} aria-label="加购名" value={a.name} onChange={(e) => upAddon(i, { name: e.target.value })} />
              <div className="flex items-center gap-1.5">
                <input className={cn(textCls, "w-20")} aria-label={`${a.name}的价格`} value={a.price} onChange={(e) => upAddon(i, { price: e.target.value })} />
                <span className="text-sm text-body">元</span>
              </div>
              <input className={textCls} aria-label={`${a.name}的说明`} value={a.note} onChange={(e) => upAddon(i, { note: e.target.value })} />
            </div>
          ))}
        </div>
        <div className="mt-4 flex flex-wrap gap-x-8 gap-y-3 text-sm text-body">
          <label className="flex items-center gap-2">
            对客承诺多说
            <input type="number" min={0} className={numCls} aria-label="对客承诺的余量" value={cfg.promise_buffer_hours} onChange={(e) => up({ promise_buffer_hours: Number(e.target.value) })} />
            小时
          </label>
          <label className="flex items-center gap-2">
            帮我找文献时限加
            <input type="number" min={0} className={numCls} value={cfg.find_refs_extra_hours} onChange={(e) => up({ find_refs_extra_hours: Number(e.target.value) })} />
            小时
          </label>
          <label className="flex items-center gap-2">
            含
            <input type="number" min={0} className={numCls} value={cfg.revisions_included} onChange={(e) => up({ revisions_included: Number(e.target.value) })} />
            轮修改
          </label>
        </div>
      </Block>

      <Block title="排期" note="加急名额、以后某天开工几点算是我的假设，可以改。">
        <div className="flex flex-wrap gap-x-8 gap-y-3 text-sm text-body">
          <label className="flex items-center gap-2">
            每天开工
            <input type="number" min={1} className={numCls} value={cfg.daily_quota} onChange={(e) => up({ daily_quota: Number(e.target.value) })} />
            单
          </label>
          <label className="flex items-center gap-2">
            交付至少比汇报早
            <input type="number" min={0} className={numCls} value={cfg.buffer_days} onChange={(e) => up({ buffer_days: Number(e.target.value) })} />
            天
          </label>
          <label className="flex items-center gap-2">
            排期最远看
            <input type="number" min={1} className={numCls} value={cfg.queue_horizon_days} onChange={(e) => up({ queue_horizon_days: Number(e.target.value) })} />
            天
          </label>
          <label className="flex items-center gap-2">
            加急每天最多
            <input type="number" min={0} className={numCls} value={cfg.rush_daily_quota} onChange={(e) => up({ rush_daily_quota: Number(e.target.value) })} />
            单
          </label>
          <label className="flex items-center gap-2">
            排到以后某天的，从
            <input type="number" min={0} max={23} className={numCls} value={cfg.work_start_hour} onChange={(e) => up({ work_start_hour: Number(e.target.value) })} />
            点开始算时限
          </label>
        </div>
      </Block>

      <Block title="没认领的访客" note="还没认领激活码的会话只问答、不收资料；聊天要花钱，每天回复有上限，超了回一句固定的话（入口话术里的 visitor_limited）。">
        <div className="flex flex-wrap gap-x-8 gap-y-3 text-sm text-body">
          <label className="flex items-center gap-2">
            每个会话每天最多回
            <input type="number" min={0} className={numCls} value={cfg.visitor_daily_limit} onChange={(e) => up({ visitor_daily_limit: Number(e.target.value) })} />
            条<Tbd />
          </label>
          <label className="flex items-center gap-2">
            全站每天最多回
            <input type="number" min={0} className={numCls} value={cfg.visitor_global_daily_limit} onChange={(e) => up({ visitor_global_daily_limit: Number(e.target.value) })} />
            条<Tbd />
          </label>
        </div>
      </Block>

      <Block title="确认收货" note="订单到「已完成」才发可编辑的 PPT 和讲稿。每个渠道认哪几种确认方式只有这一张表（平台单客人自己说确认不算，要等平台信号或你核对后点）。">
        <label className="mb-4 flex items-center gap-2 text-sm text-body">
          自有渠道交了水印版
          <input type="number" min={1} className={numCls} value={cfg.auto_confirm_days} onChange={(e) => up({ auto_confirm_days: Number(e.target.value) })} />
          天没回应视为确认
        </label>
        <label className="mb-4 flex flex-wrap items-center gap-2 text-sm text-body">
          水印浓淡
          <input
            type="number"
            min={0.08}
            max={0.4}
            step={0.01}
            className={numCls}
            value={cfg.delivery.watermark_alpha}
            onChange={(e) => up({ delivery: { ...cfg.delivery, watermark_alpha: Number(e.target.value) } })}
          />
          <span className="text-muted-foreground">样张：0.16 淡、0.20、0.22 浓；改了以后新出的水印版按新的出</span>
        </label>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[560px] text-sm">
            <thead>
              <tr className="text-left text-xs text-muted-foreground">
                <th className="py-2 pr-3 font-normal">渠道</th>
                {CONFIRM_SOURCES.map((x) => (
                  <th key={x.key} className="py-2 pr-3 font-normal">
                    {x.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {Object.entries(cfg.delivery.confirm_sources_by_platform).map(([platform, srcs]) => (
                <tr key={platform} className="border-t">
                  <td className="py-2 pr-3 text-foreground">{PLATFORM_LABEL[platform] ?? platform}</td>
                  {CONFIRM_SOURCES.map((x) => (
                    <td key={x.key} className="py-2 pr-3">
                      <input
                        type="checkbox"
                        className="accent-primary"
                        aria-label={`${PLATFORM_LABEL[platform] ?? platform}认${x.label}`}
                        checked={srcs.includes(x.key)}
                        onChange={(e) => toggleSource(platform, x.key, e.target.checked)}
                      />
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Block>

      <Block
        title="各场合要什么（资料清单）"
        note="客人看到的资料清单都从这里出：官网价目页和下单页「下单前准备好这些」、小鱼售前发的、认领后那条、场合定了发的那条、缺了点名要的。必须发的每样要选「登记成」哪种用途：客人发的文件登记成这几种都齐了，才算主材料齐（不齐不开工）。"
      >
        <MaterialsEditor cfg={cfg} purposes={settings.purposes} onChange={up} />
      </Block>

      <Block title="交付什么、注意事项" note="客人买之前原样发给他（一字不改，助手不会改写），前面一行是代码按货号算的报价。发过才能发购买方式。">
        <div className="flex flex-col gap-4">
          <label className="flex flex-col gap-1.5">
            <span className="text-sm text-foreground">交付什么</span>
            <textarea aria-label="交付什么" className={areaCls} value={cfg.deliver_text} onChange={(e) => up({ deliver_text: e.target.value })} />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-sm text-foreground">注意事项（一行一条）</span>
            <textarea aria-label="注意事项" className={areaCls} value={cfg.notes_text} onChange={(e) => up({ notes_text: e.target.value })} />
          </label>
        </div>
      </Block>

      <Block
        title="付款渠道"
        note="客户没有激活码时，助手把说明和链接原样发过去。链接和二维码都空着时，算还没设置，助手改发你的微信二维码。"
      >
        <div className="flex max-w-2xl flex-col gap-3">
          <Status ok={paymentReady} label={paymentReady ? "设置好了" : "还没设置（链接、二维码都空）"} />
          <label className="flex flex-col gap-1.5">
            <span className="text-sm text-foreground">说明</span>
            <textarea
              aria-label="付款说明"
              className={cn(areaCls, "min-h-16")}
              value={cfg.payment.text}
              onChange={(e) => up({ payment: { ...cfg.payment, text: e.target.value } })}
            />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-sm text-foreground">发卡站链接</span>
            <input
              className={textCls}
              aria-label="发卡站链接"
              placeholder="还没定"
              value={cfg.payment.link}
              onChange={(e) => up({ payment: { ...cfg.payment, link: e.target.value } })}
            />
          </label>
          <label className="flex flex-col gap-1.5">
            <span className="text-sm text-foreground">付款二维码图片（服务器上的路径，可空）</span>
            <input
              className={textCls}
              aria-label="付款二维码图片路径"
              placeholder="/app/data/assets/pay.png"
              value={cfg.payment.qr_image}
              onChange={(e) => up({ payment: { ...cfg.payment, qr_image: e.target.value } })}
            />
          </label>
        </div>
      </Block>

      <Block title="平台发货内容" note="写进小红书、闲鱼、抖音、发卡站那一单的发货内容。不许出现微信号、二维码、加微信和谐音（保存时按红线词表查）。{code} 是激活码，{url} 是兑换网址。">
        <div className="flex max-w-2xl flex-col gap-3">
          {Object.entries(cfg.delivery_templates).map(([k, v]) => (
            <label key={k} className="flex flex-col gap-1.5">
              <span className="text-sm text-foreground">{k === "code_and_url" ? "激活码 + 兑换网址" : k === "code_only" ? "只放激活码" : k}</span>
              <textarea
                aria-label={`发货内容 ${k}`}
                className={cn(areaCls, "min-h-14")}
                value={v}
                onChange={(e) => up({ delivery_templates: { ...cfg.delivery_templates, [k]: e.target.value } })}
              />
            </label>
          ))}
        </div>
      </Block>

      <Block title="哪几类回复先给你看再发" note="默认都不勾：助手的回复直接发出去。勾上的那一类会停在会话页等你点「发送」。">
        <div className="grid grid-cols-2 gap-x-6 gap-y-2 sm:grid-cols-3">
          {settings.categories.map((c) => (
            <label key={c} className="flex items-center gap-2 text-sm text-body">
              <input
                type="checkbox"
                className="accent-primary"
                checked={!!cfg.approval[c]}
                onChange={(e) => up({ approval: { ...cfg.approval, [c]: e.target.checked } })}
              />
              {c}
            </label>
          ))}
        </div>
      </Block>

      <Block title="欢迎语" note="网页聊天一打开就看到；微信客服进会话时发。">
        <textarea aria-label="欢迎语" className={cn(areaCls, "min-h-20")} value={cfg.welcome_text} onChange={(e) => up({ welcome_text: e.target.value })} />
      </Block>

      <Block title="问答卡" note="客户常问的，助手照这里答。">
        <div className="flex max-w-3xl flex-col gap-2">
          {cfg.faq.map((f, i) => (
            <div key={i} className="grid grid-cols-[1fr_1.4fr_auto] items-center gap-2">
              <input className={textCls} aria-label="问题" value={f.q} onChange={(e) => up({ faq: cfg.faq.map((x, j) => (j === i ? { ...x, q: e.target.value } : x)) })} />
              <input className={textCls} aria-label="怎么答" value={f.a} onChange={(e) => up({ faq: cfg.faq.map((x, j) => (j === i ? { ...x, a: e.target.value } : x)) })} />
              <Button variant="ghost" size="icon-sm" aria-label="删掉这条" onClick={() => up({ faq: cfg.faq.filter((_, j) => j !== i) })}>
                <X />
              </Button>
            </div>
          ))}
          <Button variant="outline" size="sm" className="self-start" onClick={() => up({ faq: [...cfg.faq, { q: "", a: "" }] })}>
            <Plus />
            加一条
          </Button>
        </div>
      </Block>

      <Block title="图片" note="你的微信二维码在 .env 的 OWNER_WECHAT_QR；付款二维码在上面「付款渠道」里填（没填用 .env 的 PAY_QR_IMAGE）。">
        <div className="flex flex-wrap gap-8">
          {(
            [
              { name: "owner_qr", label: "你的微信二维码", ok: settings.images.owner_qr },
              { name: "pay_qr", label: "付款二维码", ok: settings.images.pay_qr },
              { name: "service_qr", label: "客服二维码", ok: settings.images.service_qr },
            ] as const
          ).map((x) => (
            <div key={x.name} className="flex flex-col gap-2">
              <span className="text-sm text-foreground">{x.label}</span>
              {x.ok && imageUrl ? (
                <img src={imageUrl(x.name)} alt={x.label} className="h-32 w-32 rounded-lg border object-contain" />
              ) : (
                <span className="text-sm text-muted-foreground">还没放上来</span>
              )}
            </div>
          ))}
        </div>
      </Block>

      <Block title="企业微信「微信客服」" note={`回调地址：<网站域名>${w.callback_path}。凭证在 .env，配齐了才能收发。`}>
        <div className="flex flex-wrap gap-x-5 gap-y-2">
          <Status ok={w.corpid} label="企业 ID" />
          <Status ok={w.secret} label="Secret" />
          <Status ok={w.token} label="Token" />
          <Status ok={w.aes_key} label="EncodingAESKey" />
          <Status ok={w.open_kfid} label="客服账号 open_kfid" />
        </div>
        <div className="mt-5">
          <div className="text-sm text-foreground">进线链接（带来源，进会话时记下客户从哪来）</div>
          <div className="mt-2 flex max-w-xl items-center gap-2">
            <input className={textCls} aria-label="来源" value={scene} onChange={(e) => setScene(e.target.value)} />
            <Button
              variant="outline"
              size="sm"
              disabled={!wecomReady || !scene}
              onClick={() => {
                setLinkErr("");
                onContactWay(scene).then(setLink).catch((e) => setLinkErr(e instanceof Error ? e.message : "没生成出来"));
              }}
            >
              生成
            </Button>
          </div>
          {!wecomReady ? <p className="mt-2 text-sm text-muted-foreground">凭证还没配，生成不了</p> : null}
          {link ? <p className="mt-2 text-sm break-all text-foreground">{link}</p> : null}
          {linkErr ? <p className="mt-2 text-sm text-destructive">{linkErr}</p> : null}
        </div>
      </Block>

      <Block title="其他">
        <div className="flex flex-col gap-1.5 text-sm text-body">
          <Status ok={settings.model.configured} label={settings.model.configured ? `模型：${settings.model.name}` : "模型没配（助手不会回）"} />
          <Status
            ok={settings.production_token}
            label={settings.production_token ? "制作方接口开着（PRODUCTION_TOKEN 配了）" : "没配 PRODUCTION_TOKEN，制作方连不上助手"}
          />
          {settings.handoff_mode === "pull" ? (
            <Status
              ok={settings.factory_pull_token}
              label={
                settings.factory_pull_token
                  ? "开工时交接包存在平台里，Mac 上的 factory_pull.py 每 2 分钟来领"
                  : "交接方式是 pull，但没配 FACTORY_PULL_TOKEN，Mac 领不了"
              }
            />
          ) : (
            <span>开工时材料交到：{settings.factory_inbox}</span>
          )}
        </div>
      </Block>

      {dirty || saved ? (
        <div className="fixed inset-x-0 bottom-0 border-t bg-background md:left-52">
          <div className="flex items-center justify-end gap-3 px-6 py-3">
            {saved ? <span className="text-sm text-body">{saved}</span> : null}
            {dirty ? (
              <>
                <Button variant="ghost" size="sm" onClick={() => setCfg(settings.config)}>
                  撤销
                </Button>
                <Button size="sm" disabled={busy} onClick={() => void save()}>
                  {busy ? <Loader2 className="animate-spin" /> : null}
                  保存设置
                </Button>
              </>
            ) : null}
          </div>
        </div>
      ) : null}
    </div>
  );
}
