/** 交付页区块的示例数据（/dev/blocks 陈列用，不发请求）。图片地址留空：区块画一个占位框。 */
import type { DeliveryData, ProofRound } from "./delivery-types";

export function sampleRound(round: number, pages: number): ProofRound {
  return { round, published_at: "2026-11-18T08:00:00Z", pages: Array.from({ length: pages }, (_, i) => ({ page: i + 1, url: "" })) };
}

export const sampleDelivery: DeliveryData = {
  order_no: "00137",
  occasion: "组会文献",
  title: "卡尼曼与网络成瘾：直觉判断的两条路",
  duration_min: 20,
  present_date: "2026-11-25",
  stage: "watermarked",
  status: "已交水印版",
  step: 2,
  steps: ["收资料", "制作中", "看水印版、提修改", "确认收货", "拿最终版"],
  queue_ahead: null,
  eta_date: "2026-11-18",
  due_text: "",
  cancelled: false,
  on_hold: false,
  delivered: true,
  latest_round: 1,
  rounds: [sampleRound(1, 3)],
  revision: {
    can_submit: true, revisions_left: 1, revision_used: 0, open: false, page_count: 3, based_on_round: 1, whole_items_max: 3,
    file_max_mb: 10, after_delivery: false, hint: "含 1 轮修改：要改的地方在每页下面点「这页要改」，一次写全；提交后这一轮就用掉了。",
  },
  receipt: {
    mode: "button", hint: "没问题就点「确认收货」，确认后马上在这个页面放出可编辑的 PPT 和讲稿。", platform_name: "下单的平台",
    auto_confirm_at: "2026-11-21T08:00:00Z", auto_confirm_text: "11月21日（周六）16:00前没提修改、也没确认，会自动确认收货。", confirmed: false,
  },
  final: { released: false, waiting: false, files: [] },
  show_feedback: false,
  feedback_done: false,
};
