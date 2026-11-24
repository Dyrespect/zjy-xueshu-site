"""运维模块的接口（挂在 /api/ops）和启动时要做的事。后台看的接口在 app/admin/ops_router.py（/api/admin/ops，要登录）。

- GET /metrics：给 Prometheus 拉的计数（prometheus_client 的文本格式）。要 Authorization: Bearer <OPS_METRICS_TOKEN>；
  没配令牌 = 404（不对外）。以后装 Prometheus + Grafana 不用改代码。
lifespan：把计数器挂到请求中间件上；起调度（app/ops/scheduler.py：计数每分钟落库；告警、聚合、清理、日报、备份按 jobs.json）；
关的时候把最后不到一分钟的数也写进库。
"""

from __future__ import annotations

import asyncio
import hmac
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi.responses import PlainTextResponse

from app.core import access
from app.core.db import utcnow
from app.core.reqlog import add_observer, remove_observer
from app.ops import nodes as _nodes  # noqa: F401  登记本模块的节点
from app.ops import scheduler
from app.ops.config import kv_get, kv_set
from app.ops.runtime import get_ops

log = logging.getLogger("app.ops")
router = APIRouter()


@router.get("/metrics", include_in_schema=False, dependencies=[Depends(access.service)])  # 凭 OPS_METRICS_TOKEN
def metrics(request: Request) -> Response:
    ctx = get_ops(request.app)
    token = ctx.osettings.OPS_METRICS_TOKEN.get_secret_value()
    given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
    if not token or not hmac.compare_digest(given.encode(), token.encode()):
        return PlainTextResponse("Not Found", status_code=404)
    return Response(ctx.collector.exposition(), media_type="text/plain; version=0.0.4; charset=utf-8",
                    headers={"Cache-Control": "no-store"})


def _mark_started(app: FastAPI) -> None:
    ctx = get_ops(app)
    with ctx.database.session() as db:
        st = kv_get(db, "started")
        if not st.get("first_at"):
            kv_set(db, "started", {"first_at": utcnow().isoformat()})


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    ctx = get_ops(app)
    add_observer(app, ctx.collector.observe)
    try:
        await asyncio.to_thread(_mark_started, app)
    except Exception:  # noqa: BLE001  表还没建（没跑迁移）也让网站起来
        log.warning("运维：记启动时间失败（迁移跑了吗？）")
    running = scheduler.start(app)
    try:
        yield
    finally:
        await running.stop()
        try:
            await asyncio.to_thread(scheduler.flush_now, app)
        except Exception:  # noqa: BLE001
            log.warning("运维：关闭时落库失败")
        remove_observer(app, ctx.collector.observe)
