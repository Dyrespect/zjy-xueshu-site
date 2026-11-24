"""图库对外接口，挂在 /api/figures 下（不用登录）。后台的几个在 app/admin/figures_router.py。

启动时（lifespan）加载一次找图引擎、索引、向量和出处；加载失败时网站其余部分照常，图库接口回 503。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import APIRouter, Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.core import access
from app.core.config import Settings
from app.core.deps import client_ip, get_db, get_settings_dep, get_storage
from app.core.events import record_event
from app.core.nodes import NodeCall, run_node
from app.core.storage import Storage
from app.figures import images, overlay
from app.figures import nodes as _nodes  # noqa: F401 节点在启动时登记（figure.search、figure.contribute……）
from app.figures.inbox import FEEDBACK_REASONS, check_rate, clean, clean_text, is_bot, read_image
from app.figures.library import GROUPS, Library, get_engine, load_sources, preview_url, thumb_url
from app.figures.models import (
    FigureFeedback,
    FigureRequest,
    FigureSubmission,
    FigureTakedown,
    SearchClick,
    SearchLog,
    SiteFeedback,
)
from app.figures.node_models import ContributeIn, SearchIn
from app.figures.popular import POPULAR
from app.figures.schemas import (
    BrowseOut,
    CardsOut,
    ClickIn,
    DetailOut,
    Done,
    FeedbackIn,
    HomeOut,
    SearchOut,
    SiteFeedbackIn,
    SiteOut,
    TakedownIn,
)
from app.figures.search_service import SearchCache
from app.figures.settings import FigureSettings

log = logging.getLogger("app.figures")
router = APIRouter(dependencies=[Depends(access.public)])  # 图库全公开（规矩 24），不碰客户数据

CACHE_HEADERS = {"Cache-Control": "public, max-age=604800"}


def figure_data_dir(settings: Settings):
    return settings.DATA_DIR / "图库"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings: Settings = app.state.settings
    fs: FigureSettings = getattr(app.state, "figure_settings", None) or FigureSettings()
    app.state.figure_settings = fs
    app.state.figure_cache = SearchCache()
    try:
        engine = await run_in_threadpool(
            get_engine, settings.FIGURE_ENGINE_PATH, embed_url=settings.EMBED_URL, embed_timeout=fs.FIGURE_EMBED_TIMEOUT
        )
        sources_path = fs.FIGURE_SOURCES or figure_data_dir(settings) / "出处.json"
        sources = await run_in_threadpool(load_sources, sources_path)
        app.state.figure_library = Library(engine, settings.ACADEMIC_ROOT, sources, fs.FIGURE_ASSET_BASE)
    except Exception:
        log.exception("图库没加载起来：图库接口会回 503，网站其余部分照常")
        app.state.figure_library = None
    try:  # 叠在索引上的一层（审过的改标签、版权下架）
        with app.state.db.session() as db:
            overlay.refresh(db, app.state.figure_library, app.state.figure_cache)
    except Exception:
        log.exception("改标签、下架那一层没读出来：网站先按索引原样显示")
    yield


def figures_ctx(request: Request) -> overlay.FiguresCtx:
    """figures 节点的运行环境（图库、搜索缓存、通知）。"""
    st = request.app.state
    return overlay.FiguresCtx(getattr(st, "figure_library", None), getattr(st, "figure_cache", None), st.notifier)


# ---- 依赖 ----
def get_lib(request: Request) -> Library:
    lib = getattr(request.app.state, "figure_library", None)
    if lib is None:
        raise HTTPException(503, detail="图库暂时打不开，请稍后再试")
    return lib


def get_fs(request: Request) -> FigureSettings:
    return request.app.state.figure_settings


def _qr_path(fs: FigureSettings):
    p = fs.FIGURE_SERVICE_QR
    return p if p is not None and p.is_file() else None


# ---- 页面数据 ----
@router.get("/site", response_model=SiteOut)
def site(lib: Library = Depends(get_lib), fs: FigureSettings = Depends(get_fs)) -> dict:
    return {
        "service_url": fs.SERVICE_URL.strip(),
        "qr_url": "/api/figures/service-qr" if _qr_path(fs) else "",
        "account_note": fs.FIGURE_ACCOUNT_NOTE.strip(),
        "types": [{"code": c, "name": n} for c, n in lib.engine.names.items()],
    }


@router.get("/home", response_model=HomeOut)
def home(lib: Library = Depends(get_lib)) -> dict:
    return {
        "total": lib.total,
        "journals": lib.journals,
        "groups": lib.groups(),
        "popular": [{"label": label, "query": q} for label, q in POPULAR],
    }


@router.get("/search", response_model=SearchOut)
def search(
    request: Request,
    q: str = Query(min_length=1, max_length=200),
    code: str | None = Query(default=None, max_length=8),
    src: str = Query(default="", alias="from", max_length=32),
    visitor: str = Query(default="", alias="v", max_length=40),
    lib: Library = Depends(get_lib),
    db: Session = Depends(get_db),
):
    call = NodeCall(db, figures_ctx(request), "web")
    res = run_node("figure.search", call, SearchIn(q=q, code=code or None, caller="web", src=src, visitor=visitor))
    return res.output


@router.get("/types/{code}", response_model=BrowseOut)
def browse(
    code: str,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=40, ge=1, le=100),
    lib: Library = Depends(get_lib),
) -> dict:
    code = code.upper()
    if code not in lib.engine.names:
        raise HTTPException(404, detail="没有这个图型")
    total, cards = lib.browse(code, offset, limit)
    group_title = next(t for _, t, prefixes in GROUPS if code.startswith(prefixes))
    return {"code": code, "name": lib.type_name(code), "group_title": group_title, "total": total, "cards": cards}


@router.get("/service-qr", include_in_schema=False)
def service_qr(fs: FigureSettings = Depends(get_fs)) -> FileResponse:
    p = _qr_path(fs)
    if p is None:
        raise HTTPException(404, detail="客服二维码还没放上来")
    return FileResponse(p, headers={"Cache-Control": "no-cache"})


@router.post("/clicks", status_code=204)
def click(body: ClickIn, db: Session = Depends(get_db)) -> Response:
    if db.get(SearchLog, body.search_id) is not None:
        db.add(SearchClick(search_id=body.search_id, figure_id=body.figure_id, position=body.position, lane=body.lane))
        db.commit()
    return Response(status_code=204)


# ---- 提需求、投图、意见 ----
@router.post("/requests", response_model=Done)
async def submit_request(
    request: Request,
    want: str = Form(min_length=1, max_length=300),
    method: str = Form(default="", max_length=300),
    contact: str = Form(default="", max_length=100),
    query: str = Form(default="", max_length=300),
    search_id: int | None = Form(default=None),
    website: str = Form(default=""),
    sketch: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
    fs: FigureSettings = Depends(get_fs),
) -> dict:
    contact = clean(contact, 100)
    message = (
        "收到了。找到合适的图会通过你留的联系方式告诉你。"
        if contact
        else "收到了。补到这类图以后，搜同样的话就能找到。"
    )
    if is_bot(website):
        return {"message": message}
    want = clean_text(want, 300)
    if not want:
        raise HTTPException(400, detail="写一句想画什么图")
    ip = client_ip(request)
    check_rate(db, FigureRequest, ip, fs.FIGURE_RATE_LIMIT_PER_HOUR)
    img = await read_image(sketch, max_mb=5, required=False)
    rel = ""
    if img is not None:
        rel = storage.save(img[0], folder=f"figures/requests/{_month()}", filename=f"sketch.{img[1]}")
    row = FigureRequest(
        want=want,
        method=clean_text(method, 300),
        contact=contact,
        sketch=rel,
        query=clean(query, 300),
        search_id=search_id,
        ip=ip,
    )
    db.add(row)
    db.flush()
    record_event(db, "figures.request", f"figure_request:{row.id}", {"want": want, "query": row.query})
    db.commit()
    return {"message": message}


@router.post("/submissions", response_model=Done)
async def submit_figure(
    request: Request,
    source: str = Form(min_length=1, max_length=500),
    reason: str = Form(default="", max_length=500),
    credit: str = Form(default="", max_length=40),
    website: str = Form(default=""),
    image: UploadFile | None = File(default=None),
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
    fs: FigureSettings = Depends(get_fs),
) -> dict:
    credit = clean(credit, 40)
    message = (
        f"收到了。审核通过后收进图库，详情页会写「由 {credit} 推荐」。"
        if credit
        else "收到了。审核通过后收进图库。"
    )
    if is_bot(website):
        return {"message": message}
    source = clean_text(source, 500)
    if not source:
        raise HTTPException(400, detail="写上这张图的出处（DOI 或论文题目）")
    ip = client_ip(request)
    check_rate(db, FigureSubmission, ip, fs.FIGURE_RATE_LIMIT_PER_HOUR)
    img = await read_image(image, max_mb=10, required=True)
    assert img is not None
    rel = storage.save(img[0], folder=f"figures/submissions/{_month()}", filename=f"figure.{img[1]}")
    row = FigureSubmission(image=rel, source=source, reason=clean_text(reason, 500), credit=credit, ip=ip)
    db.add(row)
    db.flush()
    record_event(db, "figures.submission", f"figure_submission:{row.id}", {"source": source, "credit": credit})
    db.commit()
    return {"message": message}


@router.post("/site-feedback", response_model=Done)
def site_feedback(
    body: SiteFeedbackIn,
    request: Request,
    db: Session = Depends(get_db),
    fs: FigureSettings = Depends(get_fs),
) -> dict:
    contact = clean(body.contact, 100)
    message = "收到了。需要回复时会通过你留的联系方式找你。" if contact else "收到了，谢谢你的意见。"
    if is_bot(body.website):
        return {"message": message}
    content = clean_text(body.content, 1000)
    if not content:
        raise HTTPException(400, detail="写一句你的意见")
    ip = client_ip(request)
    check_rate(db, SiteFeedback, ip, fs.FIGURE_RATE_LIMIT_PER_HOUR)
    row = SiteFeedback(content=content, contact=contact, page=clean(body.page, 300), ip=ip)
    db.add(row)
    db.flush()
    record_event(db, "figures.site_feedback", f"site_feedback:{row.id}", {"content": content[:200]})
    db.commit()
    return {"message": message}


# ---- 一张图 ----
def _doc_or_404(lib: Library, fid: int) -> dict:
    d = lib.engine.doc(fid)
    if d is None or not lib.visible(fid):  # 下架的图（版权方要求删除）当作没有
        raise HTTPException(404, detail="没有这张图")
    return d


@router.get("/{fid:int}", response_model=DetailOut)
def detail(fid: int, lib: Library = Depends(get_lib)) -> dict:
    out = lib.detail(fid)
    if out is None:
        raise HTTPException(404, detail="没有这张图")
    return out


@router.get("/{fid:int}/similar", response_model=CardsOut)
def similar(fid: int, lib: Library = Depends(get_lib)) -> dict:
    _doc_or_404(lib, fid)
    return {"cards": [lib.card(d) for d in lib.engine.similar(fid, k=10) if lib.visible(d["号"])][:8]}


def _image(kind: str, fid: int, lib: Library, settings: Settings, fs: FigureSettings) -> Response:
    _doc_or_404(lib, fid)
    if lib.asset_base:  # 图在对象存储里：老链接跳过去，服务器不读原图、不在本地生成
        url = thumb_url(fid, lib.asset_base) if kind == "thumb" else preview_url(fid, lib.asset_base)
        return RedirectResponse(url, status_code=302, headers={"Cache-Control": "public, max-age=86400"})
    sub = "缩略图" if kind == "thumb" else "预览"
    try:
        p = images.ensure(kind, fid, lib.original_file(fid), figure_data_dir(settings) / sub, fs.FIGURE_WATERMARK_FONT)
    except Exception:
        log.exception("生成%s失败：图 %s", sub, fid)
        p = None
    if p is None:
        raise HTTPException(404, detail="这张图暂时打不开")
    return FileResponse(p, media_type="image/webp", headers=CACHE_HEADERS)


@router.get("/{fid:int}/thumb", include_in_schema=False)
def thumb(
    fid: int,
    lib: Library = Depends(get_lib),
    settings: Settings = Depends(get_settings_dep),
    fs: FigureSettings = Depends(get_fs),
) -> Response:
    return _image("thumb", fid, lib, settings, fs)


@router.get("/{fid:int}/preview", include_in_schema=False)
def preview(
    fid: int,
    lib: Library = Depends(get_lib),
    settings: Settings = Depends(get_settings_dep),
    fs: FigureSettings = Depends(get_fs),
) -> Response:
    return _image("preview", fid, lib, settings, fs)


@router.post("/{fid:int}/feedback", response_model=Done)
def figure_feedback(
    fid: int,
    body: FeedbackIn,
    request: Request,
    lib: Library = Depends(get_lib),
    db: Session = Depends(get_db),
    fs: FigureSettings = Depends(get_fs),
) -> dict:
    if is_bot(body.website):
        return {"message": "收到了，我们会核对这张图的标签。"}
    _doc_or_404(lib, fid)
    if body.reason not in FEEDBACK_REASONS:
        raise HTTPException(400, detail="选一项哪里不对")
    ip = client_ip(request)
    check_rate(db, FigureFeedback, ip, fs.FIGURE_RATE_LIMIT_PER_HOUR)
    data = ContributeIn(kind="tag_fix", figure_id=fid, reason=body.reason, note=body.note, query=body.query,
                        search_id=body.search_id, proposed=body.proposed.model_dump() if body.proposed else {},
                        credit=body.credit, ip=ip)
    res = run_node("figure.contribute", NodeCall(db, figures_ctx(request), "web"), data)
    if res.exit != "received":
        raise HTTPException(400, detail=res.detail)
    db.commit()
    return {"message": res.output.message}


@router.post("/takedown", response_model=Done)
def takedown(body: TakedownIn, request: Request, db: Session = Depends(get_db), fs: FigureSettings = Depends(get_fs)) -> dict:
    """版权方要求删除（页脚「版权问题」）：收到马上通知负责人，48 小时内从网站和下一版图库包里撤。"""
    if is_bot(body.website):
        return {"message": "收到了。"}
    ip = client_ip(request)
    check_rate(db, FigureTakedown, ip, fs.FIGURE_RATE_LIMIT_PER_HOUR)
    ctx = figures_ctx(request)
    ctx.takedown_hours = fs.FIGURE_TAKEDOWN_HOURS
    data = ContributeIn(kind="takedown", figures_text=body.figures, holder=body.holder, contact=body.contact,
                        note=body.reason, ip=ip)
    res = run_node("figure.contribute", NodeCall(db, ctx, "web"), data)
    if res.exit != "received":
        raise HTTPException(400, detail=res.detail)
    db.commit()
    return {"message": res.output.message}


def _month() -> str:
    return datetime.now().strftime("%Y-%m")
