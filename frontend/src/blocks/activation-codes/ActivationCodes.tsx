import { Download, Loader2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import { Button } from "@/components/ui/button";
import type { CodeGenerateIn, CodeList, CodeRow } from "@/lib/admin-types";
import { msgTime } from "@/lib/intake-types";
import { cn } from "@/lib/utils";

export type CodeStatusFilter = "all" | "unused" | "used" | "void";

export interface ActivationCodesProps {
  data: CodeList;
  status: CodeStatusFilter;
  onStatus: (s: CodeStatusFilter) => void;
  /** 货号筛选（空 = 全部） */
  sku: string;
  onSku: (sku: string) => void;
  onGenerate: (body: CodeGenerateIn) => Promise<{ batch: string; count: number }>;
  onVoid: (row: CodeRow) => Promise<void>;
  /** 下载 CSV 的地址（发卡站导入格式，一个货号一个文件） */
  exportHref: (q: { batch?: string; sku?: string }) => string;
  /** 用在哪单 → 那个客户的会话页 */
  conversationHref: (customerId: number) => string;
}

const inputCls = "h-8 rounded-md border border-input bg-background px-2.5 text-sm text-foreground outline-none focus-visible:border-ring";
const TABS: { key: CodeStatusFilter; label: string }[] = [
  { key: "all", label: "全部" },
  { key: "unused", label: "没用" },
  { key: "used", label: "用了" },
  { key: "void", label: "作废" },
];

const PLATFORMS: { key: string; label: string }[] = [
  { key: "fk", label: "发卡站" },
  { key: "xy", label: "闲鱼" },
  { key: "xhs", label: "小红书" },
  { key: "dy", label: "抖音" },
];

/** 后台激活码：按货号（时长档 × 篇数，或加购）批量生成 → 下载 CSV 导进发卡站 / 闲鱼发货工具；列表看用在哪单；
 * 没用的能作废。认领只有客人交码时由系统做。 */
export function ActivationCodes(props: ActivationCodesProps) {
  const { data } = props;
  const [sku, setSku] = useState(data.skus[0]?.sku ?? "");
  const [platform, setPlatform] = useState("fk");
  const [count, setCount] = useState("50");
  const [note, setNote] = useState("");
  const [expires, setExpires] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [made, setMade] = useState<{ batch: string; count: number; name: string } | null>(null);
  const [err, setErr] = useState("");

  async function generate() {
    setBusy("gen");
    setErr("");
    try {
      const r = await props.onGenerate({ sku, platform, count: Number(count), note: note.trim(), expires_on: expires || null });
      setMade({ ...r, name: data.skus.find((t) => t.sku === sku)?.name ?? sku });
      setNote("");
    } catch (e) {
      setErr(e instanceof Error ? e.message : "没生成出来");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-col gap-8">
      <section aria-label="生成激活码">
        <h2 className="text-base font-semibold text-foreground">生成</h2>
        <p className="mt-1 text-sm text-body">一个货号一批。生成后下载 CSV（表头 secret，一行一个码），导进发卡站或发货工具里对应的商品。平台推送付款的单不用在这里生成，付一单发一枚。</p>
        <div className="mt-4 flex flex-wrap items-end gap-3">
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">货号</span>
            <select aria-label="货号" className={cn(inputCls, "pr-7")} value={sku} onChange={(e) => setSku(e.target.value)}>
              {data.skus.map((t) => (
                <option key={t.sku} value={t.sku}>
                  {t.name}
                  {t.price ? ` · ${t.price} 元` : ""}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">在哪卖</span>
            <select aria-label="在哪卖" className={cn(inputCls, "pr-7")} value={platform} onChange={(e) => setPlatform(e.target.value)}>
              {PLATFORMS.map((p) => (
                <option key={p.key} value={p.key}>
                  {p.label}
                </option>
              ))}
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">数量</span>
            <input type="number" min={1} max={2000} className={cn(inputCls, "w-24")} value={count} onChange={(e) => setCount(e.target.value)} />
          </label>
          <label className="flex min-w-48 flex-1 flex-col gap-1 sm:max-w-64">
            <span className="text-xs text-muted-foreground">备注（可空）</span>
            <input className={inputCls} value={note} placeholder="比如：发卡站第一批" onChange={(e) => setNote(e.target.value)} />
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-xs text-muted-foreground">有效期到（可空）</span>
            <input type="date" className={inputCls} value={expires} onChange={(e) => setExpires(e.target.value)} />
          </label>
          <Button size="sm" disabled={busy === "gen" || !sku || !(Number(count) >= 1)} onClick={() => void generate()}>
            {busy === "gen" ? <Loader2 className="animate-spin" /> : null}
            生成
          </Button>
        </div>
        {err ? <p className="mt-2 text-sm text-destructive">{err}</p> : null}
        {made ? (
          <div className="mt-3 flex flex-wrap items-center gap-3 text-sm">
            <span className="text-foreground">
              生成了 {made.count} 个「{made.name}」，批次 {made.batch}
            </span>
            <Button asChild size="sm" variant="outline">
              <a href={props.exportHref({ batch: made.batch })} download>
                <Download />
                下载 CSV
              </a>
            </Button>
          </div>
        ) : null}
      </section>

      {data.batches.length ? (
        <section aria-label="最近的批次">
          <h2 className="text-base font-semibold text-foreground">最近的批次</h2>
          <ul className="mt-3 flex flex-col divide-y rounded-lg border">
            {data.batches.map((b) => (
              <li key={`${b.batch}-${b.sku}`} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5 text-sm">
                <span className="w-28 font-medium text-foreground tabular-nums">{b.batch}</span>
                <span className="w-32 text-body">{b.sku_name}</span>
                <span className="text-muted-foreground">{b.count} 个 · {msgTime(b.created_at)}</span>
                <a href={props.exportHref({ batch: b.batch })} download className="ml-auto inline-flex items-center gap-1 text-primary hover:underline">
                  <Download className="size-3.5" />
                  下载没用的
                </a>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <section aria-label="激活码列表">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 className="text-base font-semibold text-foreground">列表</h2>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <span className="text-muted-foreground">
              没用 {data.counts.unused} · 用了 {data.counts.used} · 作废 {data.counts.void}
            </span>
          </div>
        </div>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <div className="flex rounded-md border p-0.5" role="tablist" aria-label="状态">
            {TABS.map((t) => (
              <button
                key={t.key}
                type="button"
                role="tab"
                aria-selected={props.status === t.key}
                onClick={() => props.onStatus(t.key)}
                className={cn(
                  "h-7 rounded px-3 text-sm transition-colors",
                  props.status === t.key ? "bg-accent font-medium text-foreground" : "text-body hover:text-foreground",
                )}
              >
                {t.label}
              </button>
            ))}
          </div>
          <select aria-label="货号筛选" className={cn(inputCls, "pr-7")} value={props.sku} onChange={(e) => props.onSku(e.target.value)}>
            <option value="">全部货号</option>
            {data.skus.map((t) => (
              <option key={t.sku} value={t.sku}>
                {t.name}
              </option>
            ))}
          </select>
        </div>
        {data.rows.length ? (
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[720px] text-sm">
              <thead>
                <tr className="text-left text-xs text-muted-foreground">
                  <th className="py-2 pr-3 font-normal">码</th>
                  <th className="py-2 pr-3 font-normal">货号</th>
                  <th className="py-2 pr-3 font-normal">状态</th>
                  <th className="py-2 pr-3 font-normal">用在哪单</th>
                  <th className="py-2 pr-3 font-normal">批次 · 备注</th>
                  <th className="py-2 font-normal" />
                </tr>
              </thead>
              <tbody>
                {data.rows.map((r) => (
                  <tr key={r.id} className="border-t">
                    <td className="py-2.5 pr-3 font-medium text-foreground tabular-nums">{r.code}</td>
                    <td className="py-2.5 pr-3 text-body">{r.sku_name}</td>
                    <td className={cn("py-2.5 pr-3", r.status === "used" ? "text-foreground" : r.status === "void" ? "text-muted-foreground" : "text-body")}>
                      {r.status_label}
                      {r.expires_at && r.status === "unused" ? <span className="ml-1 text-xs text-muted-foreground">到 {r.expires_at.slice(0, 10)}</span> : null}
                    </td>
                    <td className="py-2.5 pr-3">
                      {r.order_id && r.customer_id ? (
                        <Link to={props.conversationHref(r.customer_id)} className="text-primary hover:underline">
                          {r.customer_name} · #{r.order_id}
                        </Link>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                      {r.used_at ? <span className="ml-2 text-xs text-muted-foreground">{msgTime(r.used_at)}</span> : null}
                    </td>
                    <td className="py-2.5 pr-3 text-muted-foreground">
                      {r.batch}
                      {r.note ? ` · ${r.note}` : ""}
                    </td>
                    <td className="py-2.5 text-right">
                      {r.status === "unused" ? (
                        <Button
                          size="xs"
                          variant="ghost"
                          disabled={busy === `v${r.id}`}
                          onClick={async () => {
                            if (!window.confirm(`作废 ${r.code}？作废了就不能再用`)) return;
                            setBusy(`v${r.id}`);
                            try {
                              await props.onVoid(r);
                            } finally {
                              setBusy(null);
                            }
                          }}
                        >
                          作废
                        </Button>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="mt-6 text-sm text-muted-foreground">还没有码</p>
        )}
      </section>
    </div>
  );
}
