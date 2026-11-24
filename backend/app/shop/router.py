"""自有网页下单的接口（挂在 /api/shop）。路由里不写判断，全转给节点 channel.web；退款不在这里（只在 /api/admin/shop）。

- GET  /catalog                  下单页：时长档、篇数档、加购、能用的付款方式（按 User-Agent）、几句提示。价全来自订单中枢设置
- POST /quote                    选了档位 → 报价（sku.quote）
- POST /checkout                 去付款 → 待付款单 + 付款指令（同一 IP 每小时最多 SHOP_IP_HOURLY_LIMIT 单）
- GET  /checkout/{view_token}    付款页每 2.5 秒问一次：付了没、码
- POST /pay/{gateway}/notify     微信 / 支付宝（本机还有 fake）的付款、退款通知，原样交给节点验签
- POST /fake/pay/{view_token}    只在 SHOP_FAKE_PAY：模拟「客人扫码付了」
- GET  /wx/oauth?t=…             微信里付款：去服务号网页授权（snsapi_base 静默）拿 openid；种 state cookie 防 CSRF
- GET  /wx/callback?t=…&code&state  授权回来：核 state → code 换 openid → JSAPI 下单 → 回付款页（openid 不落库、不进日志）
- POST /checkout/{view_token}/repay 手机浏览器点「打开微信付款」：要一个新鲜的微信 H5 链接（5 分钟有效）
- GET  /MP_verify_xxx.txt（root_router，站点根上）  公众平台配网页授权域名时要的校验文件（.env 配文件名和内容）
没配服务号 AppSecret 时 /wx/* 一律 404，微信里付款整块不出现（设计 11 第五节）。
lifespan：定时任务登记到底座调度器（超时自动确认 trigger.confirm_timeout + channel.web 的 sweep：关过期单、查退款；全集群一个在跑）。
"""

from __future__ import annotations

import logging
import re
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import date, datetime
from typing import Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import access
from app.core.deps import client_ip, get_db, get_ratelimiter, get_write_db
from app.core.events import record_event
from app.core.nodes import NodeCall, run_node
from app.shop import nodes as _nodes  # noqa: F401  登记本模块的节点
from app.shop import service, wxoauth
from app.shop.gateways import fake
from app.shop.models import CHECKOUT_STATUS_LABELS, ShopCheckout
from app.shop.models_io import TickIn, WebCheckout, WebJsapiPrepare, WebNotify, WebPoll, WebRepay, WebSweep, WebWxStart
from app.shop.runtime import ShopCtx, get_shop, shop_ctx, shop_ctx_dep

log = logging.getLogger("app.shop")


def _no_store(response: Response) -> None:
    """付款页的返回里有激活码，不许缓存（core/headers.py 的 NO_STORE_PREFIXES 还没加 /api/shop，先在这里加）。"""
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Robots-Tag"] = "noindex, nofollow"


router = APIRouter(dependencies=[Depends(_no_store)])
root_router = APIRouter()  # 站点根上的文件（main.py 不加 /api 前缀挂）：MP_verify_xxx.txt
GATEWAY_NODES = {"wechat": "pay.wechat", "alipay": "pay.alipay", "fake": "pay.fake"}
_TOKEN_RE = re.compile(r"[A-Za-z0-9_\-]{8,64}")  # 付款单令牌（secrets.token_urlsafe）：拼进跳转网址前先核样子


# ---------------------------------------------------------------- 出参（给前端和接口文档）

class TierOut(BaseModel):
    key: str
    name: str
    min_minutes: int
    max_minutes: int
    max_pages: int
    std_hours: int
    rush_hours: int | None
    rush: bool
    prices: dict[str, str | None]


class AddonOut(BaseModel):
    key: str
    name: str
    price: str | None
    note: str = ""


class MethodOut(BaseModel):
    method: str
    label: str


class CatalogOut(BaseModel):
    enabled: bool
    tiers: list[TierOut]
    bands: list[dict[str, Any]]
    addons: list[AddonOut]
    find_refs_extra_hours: int
    revisions_included: int
    auto_confirm_days: int
    page_rule_text: str
    # 下单前准备好这些：各场合必须发的、有的话更好的、每个场合都要说的（订单中枢设置里的资料清单，sku.catalog 给的）
    materials: dict[str, Any] = Field(default_factory=dict)
    methods: list[MethodOut]
    ua_kind: str
    hint: str
    # online：有配好的付款方式；platforms：自有网页暂不收款，「去付款」换成去小红书 / 闲鱼下单（店铺链接在 /api/website/config）
    pay_mode: str = "online"
    # 手机浏览器里没有能用的付款方式、但微信里能付（JSAPI 开了、H5 没开）：下单页给「复制网址到微信里打开」
    open_in_wechat: bool = False
    notices: list[str]
    site_url: str
    price_hash: str


class QuoteBody(BaseModel):
    model_config = ConfigDict(extra="ignore")  # 前端传什么价都不看

    tier: str = Field(min_length=1, max_length=16)
    band: str = Field(min_length=1, max_length=8)
    rush: bool = False
    find_refs: bool = False
    extra_revisions: int = Field(default=0, ge=0, le=5)


class QuoteResult(BaseModel):
    ok: bool
    why: str = ""
    sku: str = ""
    sku_name: str = ""
    base_price: str = ""
    addons: list[dict[str, Any]] = Field(default_factory=list)
    total: str = ""
    total_fen: int = 0
    hours: int = 0
    max_pages: int = 0
    rush_ok: bool = False
    rush_why: str = ""
    earliest_start: date | None = None
    eta_date: date | None = None
    queue_full: bool = False
    notes: list[str] = Field(default_factory=list)


class CheckoutBody(QuoteBody):
    method: str = Field(min_length=1, max_length=24)
    session_ref: str = Field(default="", max_length=64)
    source: str = Field(default="", max_length=64)
    # 付款按钮上面那三项勾选（terms_privacy / ai_processing / custom_no_refund）和协议版本；后端没勾全不建单（422）
    consents: list[str] = Field(default_factory=list, max_length=8)
    terms_version: str = Field(default="", max_length=32)
    privacy_version: str = Field(default="", max_length=32)


class PayInfo(BaseModel):
    kind: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    method: str = ""
    method_label: str = ""
    simulated: bool = False


class CheckoutView(BaseModel):
    view_token: str
    status: str
    status_label: str = ""
    total_fen: int
    expires_at: datetime | None = None
    paid_at: datetime | None = None
    pay: PayInfo
    code: str = ""
    redeem_url: str = ""
    sku_name: str = ""
    addons: list[dict[str, Any]] = Field(default_factory=list)
    hours: int = 0
    message: str = ""


class FakePayBody(BaseModel):
    drop_notify: bool = False


# ---------------------------------------------------------------- 接口

def _call(db: Session, ctx: ShopCtx, by: str = "customer") -> NodeCall:
    return NodeCall(db, ctx, by)


def _view(ctx: ShopCtx, db: Session, out: Any, message: str = "") -> CheckoutView:
    row = db.scalar(select(ShopCheckout).where(ShopCheckout.view_token == out.view_token)) if out.view_token else None
    q = dict(row.quote or {}) if row is not None else {}
    redeem = service.redeem_url(ctx.shop, row) if out.code and row is not None else ""
    return CheckoutView(view_token=out.view_token, status=out.status, status_label=CHECKOUT_STATUS_LABELS.get(out.status, out.status),
                        total_fen=out.total_fen, expires_at=out.expires_at, paid_at=out.paid_at, pay=PayInfo(**out.pay),
                        code=out.code, redeem_url=redeem, sku_name=q.get("sku_name", ""), addons=q.get("addons", []),
                        hours=q.get("hours", 0), message=message)


@router.get("/catalog", dependencies=[Depends(access.public)], response_model=CatalogOut)
def get_catalog(request: Request, db: Session = Depends(get_db), ctx: ShopCtx = Depends(shop_ctx_dep)) -> CatalogOut:
    return CatalogOut.model_validate(service.catalog(_call(db, ctx), ctx.shop, request.headers.get("user-agent", "")))


@router.post("/quote", dependencies=[Depends(access.public)], response_model=QuoteResult)
def post_quote(body: QuoteBody, db: Session = Depends(get_db), ctx: ShopCtx = Depends(shop_ctx_dep)) -> QuoteResult:
    q, why = service.quote_for(_call(db, ctx), tier=body.tier, band=body.band, rush=body.rush, find_refs=body.find_refs,
                               extra_revisions=body.extra_revisions)
    if q is None:
        return QuoteResult(ok=False, why=why)
    return QuoteResult(ok=True, **service.quote_view(q))


def _rate_limit(request: Request, ctx: ShopCtx, ip: str) -> None:
    if not get_ratelimiter(request).hit("shop.checkout", ip, limit=ctx.shop.settings.SHOP_IP_HOURLY_LIMIT, window=3600):
        raise HTTPException(429, detail="下单太频繁了，过一会儿再试")


@router.post("/checkout", dependencies=[Depends(access.public)], response_model=CheckoutView)
def post_checkout(body: CheckoutBody, request: Request, db: Session = Depends(get_db),
                  ctx: ShopCtx = Depends(shop_ctx_dep)) -> CheckoutView:
    ip = client_ip(request)
    _rate_limit(request, ctx, ip)
    req = WebCheckout(tier=body.tier, band=body.band, rush=body.rush, find_refs=body.find_refs,
                      extra_revisions=body.extra_revisions, method=body.method, session_ref=body.session_ref,
                      source=body.source, client_ip=ip, ua=request.headers.get("user-agent", "")[:512],
                      consents=body.consents, terms_version=body.terms_version, privacy_version=body.privacy_version)
    res = run_node("channel.web", _call(db, ctx), req)
    if res.exit != "ok":
        db.rollback()
        status = {"quote_rejected": 409, "pay_unavailable": 409, "consent_missing": 422}.get(res.exit, 502)
        raise HTTPException(status, detail=res.detail)
    db.commit()
    return _view(ctx, db, res.output)


MESSAGES = {
    "waiting": "", "closed": "这个付款单过期关掉了，回去重新下单就好（没付钱不会扣）。",
    "blocked": "付款收到了，但这笔没能发激活码，负责人会尽快联系退款。",
    "fail": "付款收到了，激活码还没生成好，负责人已经收到通知，会尽快处理。",
}


@router.get("/checkout/{view_token}", dependencies=[Depends(access.by_token)], response_model=CheckoutView)
def get_checkout(view_token: str, db: Session = Depends(get_write_db), ctx: ShopCtx = Depends(shop_ctx_dep)) -> CheckoutView:
    if not 8 <= len(view_token) <= 64:
        raise HTTPException(404, detail="没有这个付款单")
    res = run_node("channel.web", _call(db, ctx), WebPoll(view_token=view_token))
    if res.output is None or not res.output.view_token:
        raise HTTPException(404, detail="没有这个付款单")
    db.commit()
    return _view(ctx, db, res.output, MESSAGES.get(res.exit, ""))


async def _raw_body(request: Request) -> bytes:
    return await request.body()


@router.post("/pay/{gateway}/notify", dependencies=[Depends(access.webhook)])
def notify(gateway: str, request: Request, raw: bytes = Depends(_raw_body), db: Session = Depends(get_db),
           ctx: ShopCtx = Depends(shop_ctx_dep)) -> Response:
    node = GATEWAY_NODES.get(gateway)
    if node is None or (gateway == "fake" and not ctx.shop.settings.SHOP_FAKE_PAY):
        raise HTTPException(404, detail="Not Found")
    headers = {k: v for k, v in request.headers.items()}
    res = run_node("channel.web", NodeCall(db, ctx, f"gateway:{gateway}"), WebNotify(pay_node=node, headers=headers, raw=raw))
    db.commit()
    out = res.output
    ack, status = (out.ack, out.ack_status) if out is not None else ("fail", 500)
    if isinstance(ack, dict):
        return JSONResponse(ack, status_code=status)
    if status == 204 or (ack == "" and status < 300):
        return Response(status_code=204)
    return PlainTextResponse(str(ack), status_code=status)


@router.post("/fake/pay/{view_token}", dependencies=[Depends(access.by_token)], response_model=CheckoutView)
def fake_pay(view_token: str, body: FakePayBody, db: Session = Depends(get_db),
             ctx: ShopCtx = Depends(shop_ctx_dep)) -> CheckoutView:
    """本机走查：模拟客人扫码付了。drop_notify：只记账不发通知（测「回调丢了靠查单补」）。"""
    if not ctx.shop.settings.SHOP_FAKE_PAY:
        raise HTTPException(404, detail="Not Found")
    row = db.scalar(select(ShopCheckout).where(ShopCheckout.view_token == view_token))
    if row is None or row.pay_node != "pay.fake":
        raise HTTPException(404, detail="没有这个付款单")
    try:
        raw = fake.simulate_pay(ctx.shop, row.out_trade_no)
    except KeyError as e:
        raise HTTPException(409, detail="假网关的账本里没有这单（服务重启过），重新下单") from e
    if not body.drop_notify:
        run_node("channel.web", _call(db, ctx, "gateway:fake"), WebNotify(pay_node="pay.fake", raw=raw))
        db.commit()
    return get_checkout(view_token, db, ctx)


# ---------------------------------------------------------------- 手机上的微信付款（设计 11）

def _back(token: str, wx: str = "") -> RedirectResponse:
    """回付款页（303：跳转后用 GET 打开）；wx 是出了什么事，付款页按它说一句话、给「再试一次」。顺手清掉 state cookie。"""
    resp = RedirectResponse(f"/order/pay/{token}" + (f"?wx={wx}" if wx else ""), status_code=303)
    resp.delete_cookie(wxoauth.STATE_COOKIE, path=wxoauth.COOKIE_PATH)
    return resp


def _jsapi_or_404(ctx: ShopCtx, token: str) -> str:
    node = service.jsapi_node(ctx.shop)
    if node is None or not _TOKEN_RE.fullmatch(token):
        raise HTTPException(404, detail="Not Found")
    return node


@router.get("/wx/oauth", dependencies=[Depends(access.by_token)], include_in_schema=False)
def wx_oauth(request: Request, t: str = "", db: Session = Depends(get_write_db),
             ctx: ShopCtx = Depends(shop_ctx_dep)) -> Response:
    """微信里付款第一步：还没拿到调起参数的，种 state cookie、302 去服务号网页授权（snsapi_base，客人看不到弹框）。"""
    node = _jsapi_or_404(ctx, t)
    res = run_node("channel.web", _call(db, ctx), WebWxStart(view_token=t))
    db.commit()
    if res.exit == "fail":
        raise HTTPException(404, detail="没有这个付款单")
    if res.exit != "need_openid":  # 已经拿到参数（刷新、按了返回）、付了、关了：直接回付款页
        return _back(t)
    if service.ua_kind(request.headers.get("user-agent", "")) != "wechat":
        return _back(t, "notwechat")  # 授权页只能在微信里打开，在浏览器里打开会报错
    state = wxoauth.new_state()
    callback = f"/api/shop/wx/callback?t={t}"
    if node == "pay.fake":  # 本机走查：不连微信，直接带一个假 code 回来
        target = f"{callback}&code=FAKE{secrets.token_hex(8)}&state={state}"
    else:  # redirect_uri 必须在公众平台配的网页授权域名下：用 PUBLIC_BASE_URL（线上 https://psyppt.pilipala.zj.cn）
        target = wxoauth.authorize_url(ctx.shop.settings.WECHATPAY_APPID, ctx.public_base_url.rstrip("/") + callback, state)
    resp = RedirectResponse(target, status_code=302)
    resp.set_cookie(wxoauth.STATE_COOKIE, state, max_age=wxoauth.STATE_TTL_SEC, path=wxoauth.COOKIE_PATH, httponly=True,
                    secure=ctx.public_base_url.startswith("https://"), samesite="lax")
    return resp


@router.get("/wx/callback", dependencies=[Depends(access.by_token)], include_in_schema=False)
def wx_callback(request: Request, t: str = "", code: str = "", state: str = "", db: Session = Depends(get_write_db),
                ctx: ShopCtx = Depends(shop_ctx_dep)) -> Response:
    """授权回来：先核 state（和 cookie 里的一样才认），已经下过单的不再换（code 只能用一次），再用 code 换 openid、JSAPI 下单。"""
    node = _jsapi_or_404(ctx, t)
    if not wxoauth.state_ok(request.cookies.get(wxoauth.STATE_COOKIE), state):
        record_event(db, "shop.wx_oauth_failed", "shop:wx_oauth", {"why": "state", "by": "customer"})
        db.commit()
        return _back(t, "state")
    first = run_node("channel.web", _call(db, ctx), WebWxStart(view_token=t))
    db.commit()  # 先结束这一段（不拿着库等微信）
    if first.exit == "fail":
        raise HTTPException(404, detail="没有这个付款单")
    if first.exit != "need_openid":
        return _back(t)
    if not code:  # snsapi_base 是静默授权，正常不会没有 code；没有就当没授权上
        return _back(t, "denied")
    try:
        openid = (wxoauth.fake_openid(code) if node == "pay.fake" else
                  wxoauth.fetch_openid(ctx.shop.settings.WECHATPAY_APPID, ctx.shop.settings.mp_appsecret(), code,
                                       adapter=ctx.shop.transports.get("wechat_oauth")))
    except wxoauth.OAuthFailed as e:
        record_event(db, "shop.wx_oauth_failed", "shop:wx_oauth", {"why": e.reason, "detail": e.detail, "by": "customer"})
        db.commit()
        return _back(t, e.reason)
    res = run_node("channel.web", _call(db, ctx), WebJsapiPrepare(view_token=t, openid=openid))
    del openid
    db.commit()
    return _back(t, "order" if res.exit == "fail" else "")


@router.post("/checkout/{view_token}/repay", dependencies=[Depends(access.by_token)], response_model=CheckoutView)
def post_repay(view_token: str, request: Request, db: Session = Depends(get_db),
               ctx: ShopCtx = Depends(shop_ctx_dep)) -> CheckoutView:
    """手机浏览器（微信 H5）：点「打开微信付款」时要一个新鲜的链接；前端拿到就跳，付没付照旧只看通知和查单。"""
    if not _TOKEN_RE.fullmatch(view_token):
        raise HTTPException(404, detail="没有这个付款单")
    ip = client_ip(request)
    if not get_ratelimiter(request).hit("shop.repay", ip, limit=60, window=3600):
        raise HTTPException(429, detail="点得太频繁了，过一会儿再试")
    res = run_node("channel.web", _call(db, ctx), WebRepay(view_token=view_token, client_ip=ip))
    if res.exit == "fail" and (res.output is None or not res.output.view_token):
        db.rollback()
        raise HTTPException(404, detail=res.detail or "没有这个付款单")
    db.commit()
    if res.exit == "fail":
        raise HTTPException(502, detail="微信付款链接没要到，过一会儿再点一次；还不行就回去重新下单")
    return _view(ctx, db, res.output, MESSAGES.get(res.exit, ""))


@root_router.get("/MP_verify_{key}.txt", dependencies=[Depends(access.public)], include_in_schema=False)
def mp_verify(key: str, request: Request) -> PlainTextResponse:
    """公众平台「网页授权域名」的校验文件：放在域名根上，内容原样回（文件名、内容在 .env 的 WECHAT_MP_VERIFY_FILE / _CONTENT）。"""
    got = get_shop(request.app).settings.mp_verify()
    if got is None or got[0] != f"MP_verify_{key}.txt":
        raise HTTPException(404, detail="Not Found")
    return PlainTextResponse(got[1])


# ---------------------------------------------------------------- 定时任务

def run_tick(app: FastAPI, now: datetime | None = None) -> dict[str, Any]:
    """跑一轮：超时自动确认 + 关过期单、查退款。各自一个事务，出错只回滚自己那一段。"""
    ctx = shop_ctx(app)
    out: dict[str, Any] = {}
    database = app.state.db
    with database.session() as db:
        r = run_node("trigger.confirm_timeout", NodeCall(db, ctx, "system:auto_confirm"), TickIn(now=now))
        out["confirm"] = r.output.model_dump() if r.output else {}
    with database.session() as db:
        r = run_node("channel.web", NodeCall(db, ctx, "system:sweep"), WebSweep(now=now))
        out["sweep"] = r.output.swept if r.output else {}
    return out


def _tick_and_log(app: FastAPI) -> None:
    res = run_tick(app)
    if res.get("confirm", {}).get("completed") or any(res.get("sweep", {}).values()):
        log.info("shop 定时任务：%s", res)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    rt = get_shop(app)
    if app.state.settings.APP_ENV == "prod":
        if rt.settings.SHOP_FAKE_PAY:
            raise RuntimeError("SHOP_FAKE_PAY 只许在测试和本机开；生产 .env 里把它删掉或设成 false")
        if "pay.fake" in rt.settings.methods().values():
            raise RuntimeError("SHOP_METHODS 里有 pay.fake（假网关）：生产只许 pay.wechat / pay.alipay；"
                               "商户号没下来就让 SHOP_METHODS 空着（下单页自动引导去小红书、闲鱼）")
    if rt.settings.SHOP_TIMER_ENABLED:
        every = max(30, rt.settings.SHOP_TIMER_INTERVAL_SEC)
        app.state.scheduler.every("shop.tick", every, lambda: _tick_and_log(app), initial_delay=every)
    yield
