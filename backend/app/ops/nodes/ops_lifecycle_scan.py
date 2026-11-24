"""ops.lifecycle_scan 保存期限盘点。"""

from __future__ import annotations

from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.ops import sources
from app.ops.config import kv_set, load_config
from app.ops.models_io import Empty, LifecycleOut


def handler(call: NodeCall, data: Empty) -> NodeResult:
    cfg = load_config(call.db)
    rows, errors = sources.collect("lifecycle", call.db, cfg.lifecycle)
    out = LifecycleOut(rows=[r.model_dump() for r in rows], errors=errors)
    kv_set(call.db, "lifecycle_last", {**out.model_dump(), "at": (data.now or call.ctx.now()).isoformat()})
    return NodeResult(exit="ok", output=out)


CARD = NodeCard(
    id="ops.lifecycle_scan",
    name="保存期限盘点",
    description="每天数一遍：客户材料、水印图、最终版、聊天记录各有多少已经过了设置里的保存期限。只数不删——期限是我的建议，"
                "要等法务和财务确认；发票和付款凭证的期限「待财务确认」，不编数。",
    category="运营",
    tech=["接口位 sources.lifecycle（由 app/admin/ops_sources.py 读订单中枢的文件表、消息表）"],
    input_model=Empty,
    output_model=LifecycleOut,
    exits=[NodeExit(key="ok", label="数好了", kind="ok"), NodeExit(key="fail", label="出错", kind="fail")],
    config=["lifecycle（每类的保存天数、怎么处理、待谁确认）、lifecycle_confirmed（后台「运维 → 设置」）"],
    emits=["无"],
    listens=["无"],
    replaceable=["确认之后：换成真删的节点（要订单中枢提供删文件、删聊天正文的节点，运维不直接删业务表）"],
    failure="只读；某一类读不到写原因。",
    owner="运维",
    status="要新做",
)
register(CARD, handler)
