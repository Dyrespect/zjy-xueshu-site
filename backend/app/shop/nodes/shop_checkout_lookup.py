"""shop.checkout_lookup 查付款单（只读）。

开票模块（docs/任务单/07_开票_设计.md 第六节）提的：付款页上的发票一块要确认「这个付款页令牌就是这一单的」，
不读 shop 的表、也不靠激活码（码可能被别人看到）。只返回号和金额，不返回激活码、付款人标识。
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.shop.models import ShopCheckout


class LookupIn(BaseModel):
    view_token: str = Field(min_length=8, max_length=64, description="付款页令牌（/order/pay/<令牌>）")


class LookupOut(BaseModel):
    found: bool = False
    status: str = Field(default="", description="pending / paid / closed / refunding / refunded / part_refunded")
    order_id: int | None = Field(default=None, description="付了、建了单才有")
    amount_fen: int = 0
    paid_fen: int = 0
    refunded_fen: int = 0


def handler(call: NodeCall, data: LookupIn) -> NodeResult:
    row = call.db.scalar(select(ShopCheckout).where(ShopCheckout.view_token == data.view_token))
    if row is None:
        return NodeResult(exit="not_found", output=LookupOut())
    built = row.create_exit in ("created", "exists")
    return NodeResult(exit="ok", output=LookupOut(found=True, status=row.status, order_id=row.order_id if built else None,
                                                  amount_fen=row.amount_fen, paid_fen=row.paid_fen, refunded_fen=row.refunded_fen))


CARD = NodeCard(
    id="shop.checkout_lookup",
    name="查付款单",
    description="凭付款页令牌查这个付款单：付没付、建的是哪一单、付了多少、退了多少。只读。"
                "开票用它确认「付款页上申请发票的人就是这一单的付款人」，别的模块要凭付款页令牌认单也用它。",
    category="渠道",
    tech=["SQLAlchemy 只读查询 shop_checkouts"],
    input_model=LookupIn,
    output_model=LookupOut,
    exits=[NodeExit(key="ok", label="查到了", kind="ok"), NodeExit(key="not_found", label="没有这个付款单", kind="fail")],
    config=["无"],
    emits=["无"],
    listens=["无"],
    replaceable=["暂无"],
    failure="只读，随便重试；不返回激活码和付款人标识。调用方自己限流（防撞令牌）。",
    owner="B（开票模块提的，等主窗口确认）",
    status="要新做",
)
register(CARD, handler)
