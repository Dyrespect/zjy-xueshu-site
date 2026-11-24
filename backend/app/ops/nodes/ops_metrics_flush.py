"""ops.metrics_flush 计数落库。"""

from __future__ import annotations

from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.ops import store
from app.ops.models_io import Empty, FlushOut


def handler(call: NodeCall, data: Empty) -> NodeResult:
    ctx = call.ctx
    res = store.flush(call.db, ctx.collector, now=data.now or ctx.now(), gauge_args=(call.db, ctx.app))
    return NodeResult(exit="ok", output=FlushOut(**res))


CARD = NodeCard(
    id="ops.metrics_flush",
    name="计数落库",
    description="每分钟把这一分钟的请求数、耗时分桶、出错（5xx）、页面访问、新访客写进库（原始表 ops_samples、错误表 ops_errors），"
                "顺手记一次心跳（算可用性）；每 5 分钟读一次仪表（水印队列、做单产能、付款通知缺失）。每个网站进程各自跑。",
    category="运营",
    tech=["prometheus_client（Histogram / Counter / Gauge，进程内累计；取差值落库）", "SQLAlchemy", "请求中间件 app/core/reqlog.py 的观察者",
          "接口位 sources.gauge"],
    input_model=Empty,
    output_model=FlushOut,
    exits=[NodeExit(key="ok", label="写好了", kind="ok"), NodeExit(key="fail", label="没写进去（下一分钟连这次一起写）", kind="fail")],
    config=["OPS_METRICS_ENABLED（.env）：关了不计数", "jobs.json：flush 每 60 秒、per_process"],
    emits=["无"],
    listens=["每个请求（中间件观察者）"],
    replaceable=["装了 Prometheus 之后：Prometheus 直接拉 /api/ops/metrics 存时序，这个节点只给后台页和日报留一份"],
    failure="写库失败整批回滚，把「上次取到」退回计数器，下一分钟连这次的一起写，不丢数；同一分钟同一格重复写是相加（先查后改），不会重复插入。",
    owner="运维",
    status="要新做",
)
register(CARD, handler)
