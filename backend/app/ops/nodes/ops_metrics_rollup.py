"""ops.metrics_rollup 小时聚合。"""

from __future__ import annotations

from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.ops import store
from app.ops.models_io import Empty, RollupOut


def handler(call: NodeCall, data: Empty) -> NodeResult:
    return NodeResult(exit="ok", output=RollupOut(**store.rollup(call.db, now=data.now or call.ctx.now())))


CARD = NodeCard(
    id="ops.metrics_rollup",
    name="小时聚合",
    description="把整点以前的每分钟原始数按小时合成一行（次数、合计相加，耗时分桶逐桶相加，最大取最大），存进 ops_hourly，"
                "原始数 30 天后删掉也还能看一年的趋势。每 15 分钟跑一次。",
    category="运营",
    tech=["SQLAlchemy（只用通用写法，换 PostgreSQL 不用改）"],
    input_model=Empty,
    output_model=RollupOut,
    exits=[NodeExit(key="ok", label="合好了", kind="ok"), NodeExit(key="fail", label="出错（下一轮再来）", kind="fail")],
    config=["jobs.json：rollup 每 900 秒"],
    emits=["无"],
    listens=["无"],
    replaceable=["Prometheus 的 recording rules / 降采样（装了 Prometheus 以后）"],
    failure="从上次聚合到的那一小时接着合，那一小时重算覆盖（幂等）；出错整轮回滚，下一轮再来。",
    owner="运维",
    status="要新做",
)
register(CARD, handler)
