import { defineBlockDemo } from "@/lib/blocks";
import type { CodeList, CodeRow } from "@/lib/admin-types";

import { ActivationCodes } from "./ActivationCodes";

const at = "2026-11-18T03:12:00Z";
const skus: CodeList["skus"] = [
  { sku: "light-p1", name: "轻量 · 1 篇", price: "24.9", kind: "base" },
  { sku: "regular-p1", name: "常规 · 1 篇", price: "29.9", kind: "base" },
  { sku: "regular-p2_3", name: "常规 · 2–3 篇", price: "39.9", kind: "base" },
  { sku: "long-p1", name: "长 · 1 篇", price: "44.9", kind: "base" },
  { sku: "addon-rush", name: "加购：加急", price: "9.9", kind: "addon" },
  { sku: "addon-revision", name: "加购：再改一轮", price: "9.9", kind: "addon" },
];
const row = (o: Partial<CodeRow>): CodeRow => ({
  id: 1, code: "", sku: "regular-p1", addons: [], sku_name: "常规 · 1 篇", platform: "fk", platform_order_id: "", status: "unused",
  status_label: "没用", batch: "20261118-1", note: "", expires_at: null, order_id: null, customer_id: null, customer_name: "",
  used_at: null, voided_at: null, created_at: at, ...o,
});

const data: CodeList = {
  counts: { unused: 47, used: 2, void: 1 },
  skus,
  batches: [
    { batch: "20261118-2", sku: "addon-revision", sku_name: "加购：再改一轮", count: 20, created_at: at },
    { batch: "20261118-1", sku: "regular-p1", sku_name: "常规 · 1 篇", count: 30, created_at: at },
  ],
  rows: [
    row({ id: 50, code: "PSY-K7QM4XWDN", status: "used", status_label: "用了", note: "发卡站第一批", order_id: 31, customer_id: 18, customer_name: "杭杭吖", used_at: at }),
    row({ id: 49, code: "PSY-3HNP8RTAN", note: "发卡站第一批" }),
    row({ id: 21, code: "PSY-W9EBC2YJN", sku: "addon-revision", sku_name: "加购：再改一轮", batch: "20261118-2", status: "used", status_label: "用了", order_id: 27, customer_id: 12, customer_name: "青柚", used_at: at }),
    row({ id: 20, code: "PSY-6FUZ7GMSN", status: "void", status_label: "作废", note: "发错了", voided_at: at }),
  ],
};

const noop = async () => undefined;

export default defineBlockDemo({
  block: "activation-codes",
  title: "激活码（后台）",
  order: 54,
  component: ActivationCodes,
  examples: [
    {
      name: "生成过两批、用了两个",
      props: {
        data, status: "all", onStatus: () => undefined, sku: "", onSku: () => undefined,
        onGenerate: async () => ({ batch: "20261118-3", count: 50 }), onVoid: noop,
        exportHref: () => "#", conversationHref: (id: number) => `/admin/conversations/${id}`,
      },
    },
    {
      name: "还没有码",
      props: {
        data: { counts: { unused: 0, used: 0, void: 0 }, skus, batches: [], rows: [] }, status: "all", onStatus: () => undefined,
        sku: "", onSku: () => undefined, onGenerate: async () => ({ batch: "20261118-1", count: 50 }), onVoid: noop,
        exportHref: () => "#", conversationHref: (id: number) => `/admin/conversations/${id}`,
      },
    },
  ],
});
