import { defineBlockDemo } from "@/lib/blocks";
import type { OpsAlert } from "@/lib/ops-types";

import { OpsErrors } from "./OpsErrors";

// 示意数据，不是真数据
const alert: OpsAlert = {
  id: 7, key: "pay_notify_invalid", rule: "pay_notify_invalid", level: "urgent", level_label: "要立刻处理", title: "支付回调验签失败",
  detail: "近 60 分钟收到 2 条验签不过或对不上的支付通知", impact: "自有网页的客人可能付了钱却没建单、没拿到激活码", link: "/admin/channels",
  status: "open", first_at: "2026-11-18T05:10:00Z", last_at: "2026-11-18T05:30:00Z", count: 3, notified_at: "2026-11-18T05:10:00Z",
  notify_count: 1, resolved_at: null, resolved_by: "",
};

export default defineBlockDemo({
  block: "ops-errors",
  title: "后台：错误与告警",
  order: 96,
  component: OpsErrors,
  examples: [
    {
      name: "有告警、有错误",
      props: {
        alerts: [alert, { ...alert, id: 6, key: "disk_usage", rule: "disk_usage", level: "today", level_label: "今天看一下", title: "磁盘快满了",
          detail: "用了 82%，还剩 7.2 GB", impact: "满了以后数据库写不进", status: "resolved", resolved_at: "2026-11-18T03:00:00Z", resolved_by: "auto" }],
        errors: [
          { id: 1, at: "2026-11-18T05:12:00Z", rid: "9f2c41d07ab3e611", method: "POST", route: "/api/shop/pay/{gateway}/notify", status: 500,
            kind: "RuntimeError", message: "验签证书读不到", ms: 32 },
        ],
        slow: [
          { route: "/api/figures/search", method: "GET", n: 4210, errors_5xx: 0, avg_ms: 210, p50_ms: 160, p95_ms: 640, max_ms: 1600 },
          { route: "/api/delivery/{token}", method: "GET", n: 380, errors_5xx: 0, avg_ms: 40, p50_ms: 22, p95_ms: 90, max_ms: 200 },
        ],
        onResolve: () => undefined,
      },
    },
    { name: "都没有", props: { alerts: [], errors: [], slow: [], onResolve: () => undefined } },
  ],
});
