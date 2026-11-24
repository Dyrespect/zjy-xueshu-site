"""order.create 建单。"""

from __future__ import annotations

from pydantic import BaseModel

from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.intake import orders, pricing
from app.intake.adapters import PaidIn
from app.intake.config_store import load_config


class CreateOut(BaseModel):
    order_id: int | None = None
    code: str = ""
    sku_name: str = ""


def handler(call: NodeCall, data: PaidIn) -> NodeResult:
    try:
        res = orders.receive_paid(call.db, call.ctx, data, by=call.by)
    except ValueError as e:
        return NodeResult(exit="fail", detail=str(e))
    if res.exit == "blocked":
        return NodeResult(exit="blocked", output=CreateOut(), detail="这个买家退款作废太多次，没发码")
    cfg = load_config(call.db)
    out = CreateOut(order_id=res.order.id if res.order else None, code=res.code.code,
                    sku_name=pricing.sku_name(cfg, res.code.sku, res.code.addons or []))
    return NodeResult(exit=res.exit, output=out)


CARD = NodeCard(
    id="order.create",
    name="建单",
    description="一笔付款进来（平台已付款、自有网页付款成功）时调：生成一枚激活码；基础货号同时建一单（已付款，还没有客人认领），"
                "加购货号只发码。同一平台单号再来返回同一枚码（幂等）；同一买家退款作废太多次不再发码。",
    category="订单",
    tech=["SQLAlchemy（intake_orders、intake_activation_codes）", "流程引擎 app/intake/flow.py（放到「已付款」）",
          "调用方：渠道适配器 app/platforms/（模块 C）、自有网页付款回调（模块 B）"],
    input_model=PaidIn,
    output_model=CreateOut,
    exits=[NodeExit(key="created", label="建好了（码 + 单）", kind="ok"),
           NodeExit(key="exists", label="这个平台单号来过，返回原来的码", kind="ok"),
           NodeExit(key="blocked", label="买家退款作废太多次，不发码", kind="fail"),
           NodeExit(key="fail", label="货号不对或现在不卖", kind="fail")],
    config=["duration_tiers、paper_bands、addons：货号开不开、价多少", "refund_block_after：退款作废几次不再发码"],
    emits=["intake.order_created", "intake.paid_received", "intake.paid_blocked", "intake.stage"],
    listens=["无"],
    replaceable=["码池渠道（发卡站、闲鱼自动发货）不走这里，用 code.issue 先批量生成"],
    failure="幂等：(platform, platform_order_id) 在激活码表上唯一，重复推送返回 exists；没单号的（闲鱼）每次都发新码，"
            "要靠适配器自己去重。数据库错误抛出，调用方事务回滚后可以重试。",
    owner="A",
    status="要改",
)
register(CARD, handler)
