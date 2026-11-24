import { defineBlockDemo } from "@/lib/blocks";
import type { OpsBackups as Data } from "@/lib/ops-types";

import { OpsBackups } from "./OpsBackups";

// 示意数据，不是真数据
const config: Data["config"] = { enabled: true, time: "03:30", keep_daily: 7, keep_weekly: 4, weekly_weekday: 6, drill_every_days: 30, verify: [] };
const sample: Data = {
  engine: "builtin", restic_installed: false, cos_enabled: false, where: "/app/data/backups", error: "", restic: [], config,
  builtin: [
    { name: "app-20261118-033000", created_at: "2026-11-17T19:30:00Z", local_date: "2026-11-18", weekly: false, db_bytes: 18_400_000,
      bytes: 4_100_000, verify: { orders: 137, paid_sum: "4231.30" } },
    { name: "app-20261116-033000", created_at: "2026-11-15T19:30:00Z", local_date: "2026-11-16", weekly: true, db_bytes: 18_100_000,
      bytes: 4_000_000, verify: { orders: 130, paid_sum: "4012.40" } },
  ],
  last_done: { at: "2026-11-17T19:30:00Z", name: "app-20261118-033000", db_bytes: 18_400_000, seconds: 0.8 },
  last_failed: null,
  last_drill: { at: "2026-11-01T21:00:00Z", ok: true, backup: "app-20261102-033000", integrity: "ok", error: "",
    checks: [{ key: "orders", label: "订单数", expected: 98, actual: 98, ok: true }, { key: "paid_sum", label: "订单实付合计（元）", expected: "2990.10", actual: "2990.10", ok: true }] },
};

export default defineBlockDemo({
  block: "ops-backups",
  title: "后台：备份",
  order: 97,
  component: OpsBackups,
  examples: [
    { name: "内置兜底", props: { data: sample, busy: "", onRun: () => undefined, onDrill: () => undefined } },
    {
      name: "restic、最近一次失败",
      props: {
        data: { ...sample, engine: "restic", restic_installed: true, where: "COS psyppt-backup/db", builtin: [],
          restic: [{ id: "4f1c2a9b", time: "2026-11-17T19:30:00Z", paths: 2 }],
          last_failed: { at: "2026-11-18T19:30:00Z", error: "restic backup 失败：连不上仓库" } },
        busy: "", onRun: () => undefined, onDrill: () => undefined,
      },
    },
  ],
});
