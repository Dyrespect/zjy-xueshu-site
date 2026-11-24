"""code.issue 发码（码池批量生成；闲鱼发货工具回写平台单号）。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.intake import codes, orders, pricing
from app.intake.config_store import load_config
from app.intake.models import ActivationCode


class IssueIn(BaseModel):
    action: Literal["issue", "attach"] = Field(default="issue", description="issue 批量生成；attach 给已卖出的码回写平台单号")
    sku: str = Field(default="", description="issue：货号（基础或加购）")
    count: int = Field(default=1, ge=1, le=2000, description="issue：生成几个")
    addons: list[str] = Field(default_factory=list, description="issue：同一笔带的加购")
    platform: str = Field(default="fk", description="issue：在哪卖（fk 发卡站、xy 闲鱼……）")
    note: str = Field(default="", max_length=256)
    expires_at: datetime | None = None
    code: str = Field(default="", description="attach：哪枚码")
    platform_order_id: str = Field(default="", max_length=64, description="attach：平台单号")
    buyer_id: str = Field(default="", max_length=128)
    paid_at: datetime | None = None
    paid_amount: str = Field(default="", max_length=16)


class IssueOut(BaseModel):
    batch: str = ""
    codes: list[str] = Field(default_factory=list)


def handler(call: NodeCall, data: IssueIn) -> NodeResult:
    db = call.db
    if data.action == "attach":
        row = db.scalar(select(ActivationCode).where(ActivationCode.code == (codes.normalize_code(data.code) or "")))
        if row is None or not data.platform_order_id:
            return NodeResult(exit="fail", detail="没有这枚码，或者没给平台单号")
        try:
            orders.attach_platform_order(db, row, platform_order_id=data.platform_order_id, buyer_id=data.buyer_id,
                                         paid_at=data.paid_at, paid_amount=data.paid_amount, by=call.by)
        except ValueError as e:
            return NodeResult(exit="fail", detail=str(e))
        return NodeResult(exit="ok", output=IssueOut(codes=[row.code]))
    cfg = load_config(db)
    if data.sku not in pricing.sellable_skus(cfg) or not pricing.sku_open(cfg, data.sku, data.addons):
        return NodeResult(exit="fail", detail=f"货号「{data.sku}」现在不卖")
    batch, rows = codes.generate_batch(db, sku=data.sku, count=data.count, addons=data.addons, platform=data.platform,
                                       note=data.note, expires_at=data.expires_at, by=call.by)
    return NodeResult(exit="ok", output=IssueOut(batch=batch, codes=[r.code for r in rows]))


CARD = NodeCard(
    id="code.issue",
    name="发码",
    description="按货号批量生成激活码，给码池渠道（发卡站、闲鱼自动发货工具）导入库存；码卖出后发货工具回写平台单号也走这里。"
                "码格式 PSY- 加 9 位，去掉容易看错的字符。",
    category="订单",
    tech=["Python secrets 随机", "SQLAlchemy（intake_activation_codes）", "发卡站 Dujiao-Next 的 CSV 导入格式（后台导出）"],
    input_model=IssueIn,
    output_model=IssueOut,
    exits=[NodeExit(key="ok", label="生成了 / 回写了", kind="ok"),
           NodeExit(key="fail", label="货号不卖、码不存在、单号撞了", kind="fail")],
    config=["duration_tiers、paper_bands、addons：哪些货号能卖"],
    emits=["intake.code_generated", "intake.paid_received"],
    listens=["无"],
    replaceable=["平台推送已付款的渠道用 order.create（付一单发一枚），不用码池"],
    failure="生成在一个事务里，撞了已有的码就重抽；回写单号时 (platform, platform_order_id) 唯一，撞了返回 fail。",
    owner="A",
    status="要改",
)
register(CARD, handler)
