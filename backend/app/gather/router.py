"""聚人对外接口，挂在 /api/gather 下（不用登录，都限频）。后台的在 app/admin/gather_router.py。

- GET  /site                     统一站点地图（页头页脚、导流入口、插件名字、公众号）
- POST /visit                    来访与来源（funnel.track）
- POST /cta                      点了「做汇报 PPT」这类入口（funnel.cta）
- POST /unlock                   要全部图库（figure.unlock_request）
- GET  /unlock/{码}?visitor=     到哪一步了；**只有流程到「已发链接」才带网盘那段话**
- POST /unlock/{码}/evidence     交截图 → 流程事件 evidence → 核验 → 发链接
- POST /unlock/{码}/resend       打不开，重发最新版
- 开放接口：open_router.py；远程 MCP（官方 mcp SDK）：mcp_shell.py
"""

from __future__ import annotations

import io
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from PIL import Image
from sqlalchemy.orm import Session

from app.core import access
from app.core.deps import client_ip, get_db
from app.core.nodes import NodeCall, run_node
from app.gather import nodes as _nodes  # noqa: F401 节点和流程在启动时登记
from app.gather import ratelimit, service
from app.gather.config import load_config
from app.gather.models import FigureUnlock
from app.gather.models_io import CtaClickIn, CtaIn, UnlockIn, UnlockStartIn, UnlockView, VisitIn, VisitorIn
from app.gather.mcp_shell import lifespan as mcp_lifespan
from app.gather.mcp_shell import route as mcp_route
from app.gather.open_router import router as open_router
from app.gather.runtime import build_ctx, gather_settings
from app.gather.site import resolved

router = APIRouter()
router.include_router(open_router)
router.routes.append(mcp_route)  # 远程 MCP 外壳（官方 SDK），地址 /api/gather/mcp
lifespan = mcp_lifespan  # main.py 启动时自动调：建这个 app 的 MCPServer、跑 session_manager

ALLOWED_IMAGE = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp", "GIF": "gif"}


def _limit(request: Request, what: str, per_hour: int) -> None:
    if not ratelimit.allow(request.app.state, f"{what}:{client_ip(request)}", per_hour):
        raise HTTPException(429, detail="操作太频繁了，过一会儿再试")


@router.get("/site", dependencies=[Depends(access.public)])
def site(request: Request, section: str = "figures", db: Session = Depends(get_db)) -> dict:
    gs = gather_settings(request)
    cfg = load_config(db)
    full = service.active_pack(db, "full")
    m = resolved(gs, "figures" if section not in ("main", "app") else section)
    return {
        **m,
        "cta": {"text": cfg["cta_text"], "site_url": m["brands"]["ppt"]["href"],
                "order_url": next(i["href"] for g in m["groups"] for i in g["items"] if i["label"] == "下单")},
        "unlock_enabled": bool(cfg["unlock_enabled"]),
        "verifier": cfg["verifier"],
        "plugin_name": cfg["plugin_name"],
        "gzh_name": cfg["gzh_name"],
        "gzh_keyword": cfg["gzh_keyword"],
        "follow_note": cfg["follow_note"].replace("{gzh}", cfg["gzh_name"]).replace("{keyword}", cfg["gzh_keyword"]),
        "library_version": full.version if full else "",
        "takedown_hours": int(cfg["takedown_hours"]),
    }


@router.post("/visit", dependencies=[Depends(access.public)], status_code=204)
def visit(body: VisitIn, request: Request, db: Session = Depends(get_db)) -> Response:
    ref = urlparse(request.headers.get("referer", "")).hostname or ""
    data = body.model_copy(update={"ip": client_ip(request), "referrer_host": body.referrer_host or ref})
    ctx = build_ctx(request)
    res = run_node("funnel.track", NodeCall(db, ctx, f"visitor:{body.visitor[:12]}"), data)
    if res.exit == "counted" and res.output.share_unlock_id:
        unlock = db.get(FigureUnlock, res.output.share_unlock_id)
        if unlock is not None:  # 只有核验方式里有 share_visits 时连线才通；默认只计数
            service.emit(db, ctx, unlock, "share_visit", by="funnel", why="转发链接带来一个新访客")
    db.commit()
    return Response(status_code=204)


@router.post("/cta", dependencies=[Depends(access.public)], status_code=204)
def cta(body: CtaClickIn, request: Request, db: Session = Depends(get_db)) -> Response:
    _limit(request, "cta", 300)
    run_node("funnel.cta", NodeCall(db, build_ctx(request), "web"),
             CtaIn(placement=body.placement, target=body.target, visitor=body.visitor, record=True))
    db.commit()
    return Response(status_code=204)


def _view(db: Session, request: Request, unlock: FigureUnlock, cfg: dict) -> dict:
    gs = gather_settings(request)
    text, version = service.text_for_unlock(db, unlock, cfg, gs)
    ctx = build_ctx(request)
    share_url = f"{ctx.figures_url}/?s={unlock.share_code}"
    return UnlockView(
        share_code=unlock.share_code,
        share_text=cfg["share_text"].replace("{url}", share_url),
        stage=unlock.stage,
        stage_label=service.stage_label(unlock),
        verifier=cfg["verifier"],
        reason=unlock.verdict_reason,
        share_visits=unlock.share_visits,
        need_visits=int(cfg["share_visits_n"]) if "share_visits" in (unlock.verifiers or []) else 0,
        pack_text=text,
        pack_version=version,
        follow_note=cfg["follow_note"].replace("{gzh}", cfg["gzh_name"]).replace("{keyword}", cfg["gzh_keyword"]),
        gzh_name=cfg["gzh_name"],
        gzh_keyword=cfg["gzh_keyword"],
    ).model_dump()


def _mine(db: Session, code: str, visitor: str) -> FigureUnlock:
    unlock = service.by_code(db, code)
    if unlock is None or unlock.visitor != visitor:  # 分享码不是密码，但别让人随手查别人的
        raise HTTPException(404, detail="没有找到这次领取")
    return unlock


@router.post("/unlock", dependencies=[Depends(access.public)], response_model=UnlockView)
def unlock(body: UnlockStartIn, request: Request, db: Session = Depends(get_db)) -> dict:
    _limit(request, "unlock", gather_settings(request).GATHER_RATE_PER_HOUR)
    cfg = load_config(db)
    ctx = build_ctx(request, cfg)
    res = run_node("figure.unlock_request", NodeCall(db, ctx, f"visitor:{body.visitor[:12]}"),
                   UnlockIn(visitor=body.visitor, src=body.src, ip=client_ip(request)))
    if res.exit == "off":
        raise HTTPException(403, detail=res.detail)
    db.commit()
    return _view(db, request, db.get(FigureUnlock, res.output.unlock_id), cfg)


@router.get("/unlock/{code}", dependencies=[Depends(access.by_token)], response_model=UnlockView)
def unlock_status(code: str, visitor: str, request: Request, db: Session = Depends(get_db)) -> dict:
    return _view(db, request, _mine(db, code, visitor), load_config(db))


@router.post("/unlock/{code}/evidence", dependencies=[Depends(access.by_token)], response_model=UnlockView)
async def evidence(code: str, request: Request, visitor: str = Form(min_length=8, max_length=40),
                   image: UploadFile = File(...), db: Session = Depends(get_db)) -> dict:
    gs = gather_settings(request)
    _limit(request, "evidence", gs.GATHER_RATE_PER_HOUR)
    unlock = _mine(db, code, visitor)
    data, ext = await _read_image(image, gs.GATHER_EVIDENCE_MAX_MB)
    cfg = load_config(db)
    if unlock.stage in ("passed", "sent"):  # 已经过了：不再收截图，直接把结果给他
        return _view(db, request, unlock, cfg)
    ctx = build_ctx(request, cfg)
    ev = service.save_evidence(db, ctx.storage, unlock, data, ext, visitor)
    moved = service.emit(db, ctx, unlock, "evidence", by=f"visitor:{visitor[:12]}", why="交了截图",
                         data={"evidence_id": ev.id})
    if not moved and unlock.flow_step == "review":
        unlock.verdict_reason = "又收到一张截图，负责人看过就发链接"
    db.commit()
    return _view(db, request, unlock, cfg)


@router.post("/unlock/{code}/resend", dependencies=[Depends(access.by_token)], response_model=UnlockView)
def resend(code: str, body: VisitorIn, request: Request, db: Session = Depends(get_db)) -> dict:
    _limit(request, "resend", gather_settings(request).GATHER_RATE_PER_HOUR)
    unlock = _mine(db, code, body.visitor)
    cfg = load_config(db)
    if unlock.stage != "sent":
        raise HTTPException(409, detail="还没发过链接，先交截图")
    service.emit(db, build_ctx(request, cfg), unlock, "resend", by=f"visitor:{body.visitor[:12]}", why="打不开，重发")
    db.commit()
    return _view(db, request, unlock, cfg)


async def _read_image(upload: UploadFile, max_mb: int) -> tuple[bytes, str]:
    raw = await upload.read(max_mb * 1024 * 1024 + 1)
    if not raw:
        raise HTTPException(400, detail="选一张截图")
    if len(raw) > max_mb * 1024 * 1024:
        raise HTTPException(413, detail=f"截图不能超过 {max_mb}MB")
    try:
        with Image.open(io.BytesIO(raw)) as im:
            fmt = im.format or ""
            im.verify()
    except Exception:
        raise HTTPException(400, detail="只收图片（png、jpg、webp）") from None
    if fmt not in ALLOWED_IMAGE:
        raise HTTPException(400, detail="只收图片（png、jpg、webp）")
    return raw, ALLOWED_IMAGE[fmt]
