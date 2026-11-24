"""官网的接口（挂在 /api/website）和站点根上的两个文件（root_router，main.py 不加前缀挂）。

- GET  /api/website/config    页脚、联系我们、维护中、noindex 要的设置（全是对外公开的信息）
- POST /api/website/consent   下单页建好付款单后，记下客人勾了哪几项同意（节点 website.consent）
- GET  /robots.txt            公开开关关着：全站不让爬；开着：放开，只挡带令牌的页、后台、接口，并指向 sitemap.xml
sitemap.xml 不在这里：前端构建时由 vite-plugin-sitemap 按官网页面清单（frontend/src/lib/site-pages.ts）生成到 dist/，
随前端静态文件一起给（main.py 的前端兜底路由）。robots.txt 要跟着后台开关变，构建时定不了，所以留在后端。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core import access
from app.core.deps import client_ip, get_db, get_ratelimiter
from app.core.nodes import NodeCall, run_node
from app.website import nodes as _nodes  # noqa: F401  登记本模块的节点
from app.website.config import load_config, public_view

router = APIRouter(dependencies=[Depends(access.public)])  # 官网设置、同意留痕（规矩 24）
root_router = APIRouter(dependencies=[Depends(access.public)])

# 不让搜索引擎爬的路径前缀（带令牌的页、后台、接口、付款页）。正式开放后 robots.txt 写这些
PRIVATE_PREFIXES: tuple[str, ...] = ("/admin", "/api/", "/d/", "/b/", "/chat", "/order/pay/", "/x/", "/c/", "/me", "/login")  # /b/ 需求卡（带令牌）

CONSENT_HOURLY_LIMIT = 60  # 同一 IP 每小时最多记几次（下单本身也限频，这里只防刷库；计数在 core.ratelimit，几个进程共用）


class ConsentBody(BaseModel):
    """旧前端用的：建好付款单后再补记一次。现在下单页把勾选直接带在 POST /api/shop/checkout 里（后端没勾全不建单），
    这个接口留着兼容，只认付款单令牌。"""

    checkout_token: str = Field(min_length=8, max_length=64)
    items: list[str]
    terms_version: str
    privacy_version: str


@router.get("/config")
def site_config(response: Response, db: Session = Depends(get_db)) -> dict:
    response.headers["Cache-Control"] = "no-cache"
    return public_view(load_config(db))


@router.post("/consent")
def record_consent(body: ConsentBody, request: Request, db: Session = Depends(get_db)) -> dict:
    ip = client_ip(request)
    if not get_ratelimiter(request).hit("website.consent", ip, limit=CONSENT_HOURLY_LIMIT, window=3600):
        raise HTTPException(429, detail="操作太频繁，过一会儿再试")
    try:
        r = run_node("website.consent", NodeCall(db, None, "customer"), {
            **body.model_dump(), "ip": ip, "ua": request.headers.get("user-agent", "")[:300]})
    except Exception as e:  # 输入格式不对（NodeError 包着校验错误）
        raise HTTPException(422, detail="提交的同意信息格式不对") from e
    if r.exit != "ok":
        raise HTTPException(422, detail=r.detail)
    db.commit()
    return {"ok": True}


def _base(request: Request) -> str:
    return request.app.state.settings.PUBLIC_BASE_URL.rstrip("/")


@root_router.get("/robots.txt", include_in_schema=False)
def robots(request: Request, db: Session = Depends(get_db)) -> PlainTextResponse:
    try:
        indexable = load_config(db).indexable
    except SQLAlchemyError:  # 库还没迁移（刚部署、测试里没跑迁移）：按没开放处理，宁可不让爬
        db.rollback()
        indexable = False
    if not indexable:
        body = "# 网站还没正式开放给搜索引擎（后台「官网」页的开关）\nUser-agent: *\nDisallow: /\n"
    else:
        lines = ["User-agent: *", "Allow: /", *[f"Disallow: {p}" for p in PRIVATE_PREFIXES], f"Sitemap: {_base(request)}/sitemap.xml"]
        body = "\n".join(lines) + "\n"
    return PlainTextResponse(body, headers={"Cache-Control": "no-cache"})
