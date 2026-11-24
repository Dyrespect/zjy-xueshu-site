"""插件三个外壳里的开放接口（/open/v1/*，给 skill 在线模式和以后的智能体平台）；远程 MCP 外壳在 mcp_shell.py。

底下都是 figure.ai_tool → figure.search，和网站搜索框同一个节点。不收费、不用登录、每个 IP 限频。
对外名字在后台「聚人设置」的 plugin_name（默认「PsyEngine 图库插件」）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.core import access
from app.core.deps import client_ip, get_db
from app.core.nodes import NodeCall, run_node
from app.gather import ratelimit
from app.gather.config import load_config
from app.gather.models_io import OpenFindOut as FindOut
from app.gather.runtime import GatherCtx, build_ctx, gather_settings
from app.gather.site import order_url

router = APIRouter()
open_v1 = APIRouter(prefix="/open/v1", tags=["插件：开放接口"], dependencies=[Depends(access.public)])  # 图库开放接口：公开


def _ctx(request: Request, db: Session) -> GatherCtx:
    cfg = load_config(db)
    ctx = build_ctx(request, cfg)
    gs = ctx.settings
    ctx.ai_note = cfg["ai_note"].replace("{figures_url}", ctx.figures_url).replace("{order_url}", order_url(gs, "ai"))
    return ctx


def _check_rate(request: Request, ctx: GatherCtx) -> None:
    if not ratelimit.allow(request.app.state, f"open:{client_ip(request)}", ctx.settings.OPEN_API_RATE_PER_HOUR):
        raise HTTPException(429, detail=f"今天查得太多了，去网站上接着找：{ctx.figures_url}")


def _client(request: Request, client: str) -> tuple[str, str]:
    name = (client or request.headers.get("x-client") or request.headers.get("user-agent") or "")[:60]
    return ("skill" if name.lower().startswith("psyengine-skill") else "open"), name


def _find_args(**kw: Any) -> dict[str, Any]:
    """figure.ai_tool 的入参（run_node 按说明卡里的模型校验；这里不 import figures）。"""
    return kw


def _run(request: Request, db: Session, data: dict[str, Any], ctx: GatherCtx | None = None) -> FindOut:
    ctx = ctx or _ctx(request, db)
    who = f"{data.get('caller', 'open')}:{str(data.get('client', ''))[:20]}"
    res = run_node("figure.ai_tool", NodeCall(db, ctx, who), data)
    if res.exit == "off":
        raise HTTPException(503, detail="图库暂时打不开，请稍后再试")
    db.commit()
    if res.exit == "not_found":
        raise HTTPException(404, detail="没有这张图")
    return FindOut.model_validate(res.output.model_dump())


@open_v1.get("/find", response_model=FindOut, summary="一句话找图")
def find(request: Request, q: str = Query(min_length=1, max_length=200, description="想画什么图，一句话"),
         code: str | None = Query(default=None, max_length=8, description="图型代号（先调 /types 看有哪些）"),
         n: int = Query(default=12, ge=1, le=20), client: str = Query(default="", max_length=60),
         db: Session = Depends(get_db)) -> FindOut:
    ctx = _ctx(request, db)
    _check_rate(request, ctx)
    caller, name = _client(request, client)
    return _run(request, db, _find_args(op="find", q=q, code=code, n=n, caller=caller, client=name), ctx)


@open_v1.get("/types", response_model=FindOut, summary="有哪些图型")
def types(request: Request, db: Session = Depends(get_db)) -> FindOut:
    ctx = _ctx(request, db)
    _check_rate(request, ctx)
    return _run(request, db, _find_args(op="types"), ctx)


@open_v1.get("/figure/{fid}", response_model=FindOut, summary="一张图的出处和详情页")
def figure(fid: int, request: Request, db: Session = Depends(get_db)) -> FindOut:
    ctx = _ctx(request, db)
    _check_rate(request, ctx)
    return _run(request, db, _find_args(op="figure", id=fid), ctx)


@open_v1.get("/openapi.json", include_in_schema=False)
def openapi(request: Request, db: Session = Depends(get_db)) -> JSONResponse:
    """开放接口的文档（生产也开：给 skill、智能体平台读；和关掉的整站接口清单分开）。"""
    cfg = load_config(db)
    spec = get_openapi(title=cfg["plugin_name"], version="1", routes=open_v1.routes,
                       description="心理学科研图库：一句话找论文里的图，每张带出处和网站详情页。不收费，每个 IP 限频。")
    base = gather_settings(request).SITE_FIGURES_URL.strip().rstrip("/") or str(request.base_url).rstrip("/")
    spec["servers"] = [{"url": f"{base}/api/gather"}]
    return JSONResponse(spec)


router.include_router(open_v1)
