import type { InvoiceMetrics } from "@/lib/invoice-types";

export interface InvoiceMetricsStripProps {
  metrics: InvoiceMetrics;
}

function Cell({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5 px-4 py-3">
      <span className="text-xs text-muted-foreground">{label}</span>
      <span className="text-lg font-semibold text-foreground tabular-nums">{value}</span>
      {sub ? <span className="text-xs text-muted-foreground">{sub}</span> : null}
    </div>
  );
}

/** 评估数据一条：开票申请率、平均出票用时、待开票、待发通知（周报用同一份数）。只吃 props。 */
export function InvoiceMetricsStrip({ metrics: m }: InvoiceMetricsStripProps) {
  const rate = m.request_rate === null ? "—" : `${Math.round(m.request_rate * 100)}%`;
  return (
    <div className="grid grid-cols-2 divide-x divide-y rounded-lg border sm:grid-cols-4 sm:divide-y-0" data-testid="invoice-metrics">
      <Cell label={`近 ${m.days} 天开票申请率`} value={rate} sub={`完成 ${m.completed_orders} 单，${m.orders_with_request} 单要发票`} />
      <Cell
        label="平均出票用时"
        value={m.issue_hours_avg === null ? "—" : `${m.issue_hours_avg} 小时`}
        sub={m.issued ? `开了 ${m.issued} 张，最长 ${m.issue_hours_max} 小时` : "这段时间没开"}
      />
      <Cell label="待开票" value={`${m.pending_now} 张`} sub={m.pending_oldest_hours === null ? "" : `最久的等了 ${m.pending_oldest_hours} 小时`} />
      <Cell label="待发的通知" value={`${m.notices_pending} 条`} sub="邮件服务还没有，复制去发" />
    </div>
  );
}
