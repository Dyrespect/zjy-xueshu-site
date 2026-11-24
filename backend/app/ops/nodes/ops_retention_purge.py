"""ops.retention_purge 按保留期清理。"""

from __future__ import annotations

from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.ops import retention
from app.ops.config import load_config
from app.ops.models_io import Empty, PurgeOut


def handler(call: NodeCall, data: Empty) -> NodeResult:
    out = retention.purge(call.db, load_config(call.db), now=data.now or call.ctx.now(), tzname=call.ctx.osettings.OPS_TIMEZONE)
    return NodeResult(exit="ok", output=PurgeOut(deleted=out))


CARD = NodeCard(
    id="ops.retention_purge",
    name="按保留期清理",
    description="每天 04:10 按设置里的保留期删运维数据：原始计数 30 天、小时聚合 1 年、最近错误 30 天、访客散列 2 天、关掉的告警 180 天。"
                "删原始数之前先确认那几小时已经聚合过。业务的事件记录（events）是申诉凭据，不在这里删。",
    category="运营",
    tech=["SQLAlchemy delete"],
    input_model=Empty,
    output_model=PurgeOut,
    exits=[NodeExit(key="ok", label="删好了", kind="ok"), NodeExit(key="fail", label="出错（明天再来）", kind="fail")],
    config=["retention.raw_days / hourly_days / errors_days / visitors_days / alerts_days（后台「运维 → 设置」）"],
    emits=["无"],
    listens=["无"],
    replaceable=["暂无"],
    failure="一个事务里删完；出错整个回滚、明天再来。只删运维自己的表。",
    owner="运维",
    status="要新做",
)
register(CARD, handler)
