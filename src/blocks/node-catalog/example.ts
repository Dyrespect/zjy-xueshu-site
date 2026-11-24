import { defineBlockDemo } from "@/lib/blocks";
import type { NodeCatalog as Catalog } from "@/lib/admin-types";

import { NodeCatalog } from "./NodeCatalog";

const catalog: Catalog = {
  categories: ["订单", "关口"],
  nodes: [
    {
      id: "order.claim", name: "认领", category: "订单", owner: "A", status: "要改", runnable: true, flows: ["paid_custom"],
      description: "会话交出激活码：基础码绑到这一单（码池的码现建一单），会话里还没挂单的消息挂上，订单进「已认领」；加购码挂到这个人最近活跃的那单。",
      tech: ["SQLAlchemy 带条件的 UPDATE（第一条语句，原子）", "intake_code_redemptions（code 唯一）"],
      input: { model: "ClaimIn", fields: [{ name: "customer_id", type: "int", required: true, description: "交码的会话" }, { name: "code", type: "str", required: true, description: "客人发来的码，原样" }] },
      output: { model: "ClaimOut", fields: [{ name: "result", type: "str", required: true, description: "ok | not_found | used | void | expired | wrong | legacy | locked" }] },
      exits: [{ key: "ok", label: "认领上了", kind: "ok" }, { key: "fail", label: "码不对、用过、作废", kind: "fail" }, { key: "wait", label: "错太多次锁着", kind: "wait" }],
      config: ["无"], emits: ["intake.code_redeemed", "intake.order_claimed"], listens: ["无"],
      replaceable: ["入口模块的 entry.route、兑换网页接手后都调这个节点"], failure: "幂等：同一会话再交算成功；两个人同时交只成一个。",
    },
    {
      id: "gate.final", name: "最终版发放", category: "关口", owner: "E（第一期 A 做关口）", status: "要新做", runnable: true, flows: ["paid_custom"],
      description: "订单到「已完成」才发最终版（可编辑的 pptx、讲稿），订单进「已交付」。不是已完成一律不发。",
      tech: ["orders.release_final（先过 require_completed）"],
      input: { model: "FinalIn", fields: [{ name: "order_id", type: "int", required: true, description: "" }] },
      output: { model: "FinalOut", fields: [{ name: "released", type: "bool", required: true, description: "" }] },
      exits: [{ key: "released", label: "发了", kind: "ok" }, { key: "wait", label: "还没有最终版文件", kind: "wait" }],
      config: ["无"], emits: ["intake.final_released"], listens: ["final_ready"], replaceable: ["自有渠道以后可以换成「先付尾款再发」"],
      failure: "关口在函数里，检查 4 拦住别处绕开。",
    },
  ],
  flows: [
    {
      key: "paid_custom", subject: "order", name: "付费定制主流程", start: "paid", description: "付款 → 认领 → 收资料 → 开工 → 水印版 → 已完成 → 最终版。",
      stages: [{ key: "paid", label: "已付款" }, { key: "claimed", label: "已认领" }],
      steps: [
        { id: "paid", stage: "paid", stage_label: "已付款", node: "order.create", enter: null, label: "等客人来认领", terminal: false,
          edges: [{ on: "claimed", to: "claimed", manual: false, loop: false, label: "", when: [] }, { on: "voided", to: "void", manual: false, loop: false, label: "", when: [] }] },
        { id: "claimed", stage: "claimed", stage_label: "已认领", node: "order.claim", enter: null, label: "认领了，等第一份资料", terminal: false,
          edges: [{ on: "changed", to: "gate", manual: false, loop: false, label: "", when: [] }] },
      ],
    },
  ],
};

export default defineBlockDemo({
  block: "node-catalog",
  title: "节点目录（后台）",
  order: 57,
  component: NodeCatalog,
  examples: [{ name: "两张说明卡 + 一个流程", props: { catalog } }],
});
