import { defineBlockDemo } from "@/lib/blocks";
import type { OrderDetail } from "@/lib/admin-types";

import { OrderCard } from "./OrderCard";

const noop = async () => undefined;
const now = new Date().toISOString();
const track = [
  { key: "paid", label: "已付款" }, { key: "claimed", label: "已认领" }, { key: "collecting", label: "收资料" },
  { key: "making", label: "制作中" }, { key: "watermarked", label: "已交水印版" }, { key: "revising", label: "修改中" },
  { key: "completed", label: "已完成" }, { key: "delivered", label: "已交付" },
];

const collecting: OrderDetail = {
  id: 18, status: "collecting", status_label: "收资料", stage: "collecting", flow_key: "paid_custom", flow_step: "collecting",
  stage_track: track, progress: "资料齐（按清单）：还要：哪天汇报",
  manual: [{ on: "start_now", to: "making", stage: "making", stage_label: "制作中", label: "现在开工（不等条件齐、不等排到那天）" }],
  can_void: true, can_return_code: true, voided_from: "", voided_from_label: "", void_reason: "", hold_reason: "",
  platform: "xy", platform_order_id: "XY20261118001", buyer_id: "a91c2e", source: "gzh_article", paid_at: now, paid_amount: "39.80",
  claimed_at: now, platform_completed_at: null, completed_at: null,
  sku: "regular-p1", sku_name: "常规 · 1 篇 + 加急", addons: [{ key: "rush", name: "加急", by: "bundle", code: "" }],
  max_pages: 30, due_hours: null, page_rule: "页数按内容页算，不含封面、目录、过渡页、参考文献、致谢",
  occasion: "组会文献", title: "", duration_min: 20, duration_default: false, duration_confirmed: false, paper_count: 1, page_count: null,
  present_date: null, present_date_text: "", school: "", language: "", structure_req: "总体大概在20页上下", quoted_price: "39.8",
  tier_key: "regular", tier_name: "常规", code: "PSY-K7QM4XWDN", redeemed_at: now, revisions_left: 1, extra_revisions: 0,
  rush: false, rush_by_edison: false, maker_state: "", production: [],
  requirement_quotes: ["1. 背景与问题\n2. 思路与方法\n3. 实验与结果\n4. 讨论与结论"],
  needs: [{ type: "档位", detail: "客户说要讲 30 页，买的常规档最多 30 页，问能不能多几页", at: now, resolved: false }],
  required: [{ purpose: "论文", ok: true }], optional_hint: "",
  materials: [
    { id: 41, name: "26_Persson_et_al_2021_Replication_motivated_numeracy.pdf", size: 700015, purpose: "论文", note: "", role: "material", round: 0, url: "#", is_image: false },
  ],
  conditions: [
    { key: "materials", name: "资料齐（按清单）", ok: false, detail: "还要：哪天汇报" },
    { key: "duration", name: "时长定了", ok: true, detail: "20 分钟" },
    { key: "fit", name: "档位对得上", ok: true, detail: "常规 · 1 篇，30 页以内" },
    { key: "deadline", name: "截止时间可行", ok: false, detail: "还不知道哪天汇报" },
    { key: "quota", name: "有名额", ok: true, detail: "最早 11月18日 开工（那天已排 1/3）" },
  ],
  plan: { start_date: "2026-11-18", eta_date: "2026-11-18" }, queued: false, start_date: null, eta_date: null,
  started_at: null, handoff_folder: "", handoff: null, handoff_mode: "direct", deliverables: [], pages: 0, delivery_round: 0, delivered_at: null,
  has_new_deliverable: false, can_submit_package: false, revisions: [], received_at: null, feedback: null, finished_at: null,
  delivery_url: "http://127.0.0.1:5175/d/q8Hc2vYtW1nM0aXbLr4sK7pE9dJf", created_at: now,
};

const watermarked: OrderDetail = {
  ...collecting, id: 9, status: "revising", status_label: "修改中", stage: "revising", flow_step: "revising", platform: "fk",
  platform_order_id: "", paid_amount: "", sku_name: "常规 · 1 篇", addons: [], quoted_price: "29.9", needs: [],
  progress: "改第 1 版", can_return_code: false, occasion: "会议", duration_min: 12, present_date: "2026-12-14",
  manual: [{ on: "completed", to: "confirm", stage: "completed", stage_label: "已完成", label: "确认收货（平台已完成、客人说收到了）" }],
  maker_state: "改稿中", revisions_left: 0, due_hours: 5, queued: true, start_date: "2026-11-15", eta_date: "2026-11-15", started_at: now,
  handoff_folder: "Cici",
  handoff: { id: 4, mode: "direct", status: "direct", status_label: "直接写入", folder: "Cici", files: ["CFPS研究.docx"], size: 0, created_at: now, claimed_at: null, claimed_folder: "" },
  conditions: [],
  production: [
    { id: 1, direction: "to_maker", kind: "开单说明", author: "system", read_at: now, relayed_at: null, created_at: now, files: [],
      text: "档位：常规 · 1 篇；页数上限 30 页（页数按内容页算，不含封面、目录、过渡页、参考文献、致谢）\n场合：会议\n时长：12 分钟\n交付：开工后 5 小时内交第一版水印版\n\n材料在：inbox/Cici/" },
    { id: 4, direction: "to_sales", kind: "成品", author: "maker", read_at: null, relayed_at: now, created_at: now, files: [], text: "交了第 1 版：CFPS_会议汇报.pptx、讲稿.docx，整页图 18 张" },
    { id: 5, direction: "to_maker", kind: "改稿单", author: "system", read_at: null, relayed_at: null, created_at: now, files: [],
      text: "改稿单 · 第 1 版 → 第 2 版（客户在交付页提的）· 请在 3 小时内交下一版\n1. 第 6 页：结果图换成原文的图 3\n2. 整体：配色再深一点" },
  ],
  deliverables: [
    { id: 60, name: "第1版_第01页_预览.jpg", size: 250_000, purpose: "水印版", note: "", role: "deliverable", round: 1, url: "#", is_image: true },
    { id: 61, name: "CFPS_会议汇报.pptx", size: 3_480_000, purpose: "PPT", note: "", role: "deliverable", round: 1, url: "#", is_image: false },
    { id: 62, name: "讲稿.docx", size: 41_000, purpose: "讲稿", note: "", role: "deliverable", round: 1, url: "#", is_image: false },
  ],
  delivery_round: 1, delivered_at: now,
  revisions: [{ id: 3, text: "1. 第 6 页：结果图换成原文的图 3\n2. 整体：配色再深一点", items: [{ page: 6, text: "结果图换成原文的图 3" }, { page: null, text: "配色再深一点" }], free: true, status: "open", created_at: now, files: [] }],
};

const voided: OrderDetail = {
  ...collecting, id: 22, status: "void", status_label: "作废", stage: "void", flow_step: "void", manual: [], can_void: false,
  can_return_code: false, voided_from: "making", voided_from_label: "制作中", void_reason: "refund",
  progress: "作废（退款，码作废），停在「制作中」", needs: [], conditions: [],
};

const props = (order: OrderDetail) => ({
  order, occasions: ["组会文献", "课程文献", "开题", "中期", "答辩", "会议", "其他"],
  purposes: ["论文", "开题报告", "进展", "材料", "数据", "模板", "其他"],
  deliverableKinds: ["水印版", "PPT", "讲稿", "PDF", "可编辑图", "其他", "页图"],
  onPatch: noop, onRush: noop, onResolveNeed: noop, onPurpose: noop, onPush: noop, onVoid: noop, onUpload: noop,
  onLoadFactoryJobs: async () => [], onPickFactory: noop, onDeliver: noop, onDiscard: noop, onReleaseFinal: noop,
});

export default defineBlockDemo({
  block: "order-card",
  title: "订单卡（后台）",
  order: 53,
  component: OrderCard,
  examples: [
    { name: "闲鱼单：认领了在收资料（带加急，发了你微信）", props: props(collecting) },
    { name: "交了水印版、客户提了逐页修改（制作方会话）", props: props(watermarked) },
    { name: "退款作废：停在制作中", props: props(voided) },
  ],
});
