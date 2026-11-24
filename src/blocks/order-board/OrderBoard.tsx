import type { ReactNode } from "react";
import { Link } from "react-router";

import type { OrderRow } from "@/lib/admin-types";
import { cnDate } from "@/lib/intake-types";

export interface OrderBoardProps {
  rows: OrderRow[];
  /** 点卡片去哪（这单的会话）；平台付了款、还没人认领的单没有会话，不能点 */
  hrefFor: (row: OrderRow) => string | null;
}

/** 按订单状态分列（默认流程 paid_custom 的状态，11-18 Edison 定的那一串）；作废、旧草稿只在下面数一下 */
const COLUMNS: { stage: string; title: string }[] = [
  { stage: "paid", title: "已付款" },
  { stage: "claimed", title: "已认领" },
  { stage: "collecting", title: "收资料" },
  { stage: "making", title: "制作中" },
  { stage: "watermarked", title: "已交水印版" },
  { stage: "revising", title: "修改中" },
  { stage: "completed", title: "已完成" },
  { stage: "delivered", title: "已交付" },
];

const PLATFORM: Record<string, string> = { xy: "闲鱼", xhs: "小红书", dy: "抖音", web: "网页单", fk: "发卡站", manual: "手动开单", legacy: "旧单" };

function where(r: OrderRow): string {
  if (r.channel === "wecom") return "微信";
  if (r.channel === "web") return "网页";
  return PLATFORM[r.platform] ?? "";
}

function Card({ r, href }: { r: OrderRow; href: string | null }) {
  const body: ReactNode = (
    <>
      <div className="flex items-baseline justify-between gap-2">
        <span className="truncate text-sm font-medium text-foreground">{r.name}</span>
        <span className="shrink-0 text-xs text-muted-foreground">{where(r)}</span>
      </div>
      {r.sku_name ? <div className="mt-0.5 text-sm text-foreground">{r.sku_name}</div> : null}
      <div className="mt-0.5 text-xs text-muted-foreground">
        {r.occasion || "场合没说"}
        {r.duration_min ? ` · ${r.duration_min} 分钟` : ""}
        {r.present_date ? ` · ${cnDate(r.present_date, false)}汇报` : ""}
      </div>
      {r.progress ? <div className="mt-1 text-xs leading-snug text-body">{r.progress}</div> : null}
      {r.pending || r.needs || r.rush || r.hold_reason || r.has_new_deliverable ? (
        <div className="mt-1.5 flex flex-wrap gap-x-2 text-xs">
          {r.hold_reason ? <span className="font-medium text-destructive">暂停：{r.hold_reason}</span> : null}
          {r.pending ? <span className="font-medium text-primary">{r.pending} 条待批</span> : null}
          {r.needs ? <span className="text-foreground">发了你微信 {r.needs}</span> : null}
          {r.has_new_deliverable ? <span className="text-foreground">新一版到了</span> : null}
          {r.rush ? <span className="text-foreground">加急</span> : null}
        </div>
      ) : null}
    </>
  );
  const cls = "block rounded-lg border bg-background px-3 py-2.5";
  return href ? (
    <Link to={href} className={`${cls} hover:bg-accent`}>
      {body}
    </Link>
  ) : (
    <div className={cls}>{body}</div>
  );
}

/** 订单看板：按订单状态分列（已付款 → 已交付）。点卡片进这个客户的会话（订单卡在会话页右边）。 */
export function OrderBoard({ rows, hrefFor }: OrderBoardProps) {
  const voided = rows.filter((r) => r.stage === "void").length;
  const drafts = rows.filter((r) => r.stage === "").length;
  return (
    <div>
      <div className="flex gap-3 overflow-x-auto pb-3">
        {COLUMNS.map((col) => {
          const items = rows.filter((r) => r.stage === col.stage);
          return (
            <section key={col.stage} className="flex min-w-[136px] flex-1 flex-col" aria-label={col.title}>
              <h2 className="mb-2 flex items-baseline gap-1.5 px-1 text-sm font-medium text-foreground">
                {col.title}
                <span className="text-xs font-normal text-muted-foreground">{items.length}</span>
              </h2>
              <ul className="flex flex-col gap-2">
                {items.map((r) => (
                  <li key={r.id}>
                    <Card r={r} href={hrefFor(r)} />
                  </li>
                ))}
              </ul>
            </section>
          );
        })}
      </div>
      {voided || drafts ? (
        <p className="mt-2 px-1 text-xs text-muted-foreground">
          {voided ? `另有 ${voided} 单作废` : ""}
          {voided && drafts ? "，" : ""}
          {drafts ? `${drafts} 单旧草稿（11-18 之前没付款就建的单）` : ""}
        </p>
      ) : null}
    </div>
  );
}
