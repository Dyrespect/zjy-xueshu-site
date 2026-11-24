"""channel.web 背后的实现：价目、报价、下单（待付款单）、付款页轮询、网关通知、后台退款、定时关过期单。

规矩（设计第六节 channel.web 的 failure）：
- 金额只认服务端：应付 = sku.quote 的合计，前端传什么价都不看；网关说的实付和应付对不上不建单。
- 回调幂等两层：shop_notifications.dedupe_key 唯一 + order.create 按（web, 商户订单号）幂等。
- 并发：要改待付款单之前先「占锁」（UPDATE 一下这一行，SQLite 同时只有一个写的），拿到锁再重新读一遍，
  所以通知和轮询查单同时到也只建一单；调网关（联网）一律放在占锁之前，不拿着锁等网络。
- 退款：先在本表记一笔「退款中」并提交，再去网关退；退成了才作废订单（反过来会出现单作废了钱没退）。
- 手机上的微信付款（docs/任务单/11_手机微信支付_设计.md）：微信里（JSAPI）先建待付款单、去服务号网页授权拿 openid、回来再下单；
  手机浏览器（H5）先建待付款单、客人点「打开微信付款」时才要 h5_url（只有 5 分钟有效）。付没付一律只看验过签的通知和查单，
  前端（WeixinJSBridge 的 ok、H5 跳回来）只用来换页面、催一次查单，不改任何状态。
"""

from __future__ import annotations

import hashlib
import re
import secrets
import string
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError

from app.core import net
from app.core.db import utcnow
from app.core.events import list_events, record_event
from app.core.nodes import NodeCall, NodeError, NodeResult, has_handler, run_node
from app.intake import pricing
from app.shop.adapter import WebAdapter, fen_to_amount
from app.shop.models import CHECKOUT_STATUS_LABELS, ShopCheckout, ShopNotification, ShopRefund
from app.shop.models_io import (PayClose, PayCreate, PayNotify, PayOut, PayQuery, PayRefund, PayRefundQuery, WebCheckout,
                                WebJsapiPrepare, WebNotify, WebOut, WebRefund, WebRepay, WebWxStart)
from app.shop.settings import METHOD_LABELS, METHOD_UA

BEIJING = ZoneInfo("Asia/Shanghai")
# 先建待付款单、晚一步才去网关下单的付款方式 → 还没下单时的 pay_kind（设计 11 第四节）：
#   wechat_jsapi → oauth：要先去服务号网页授权拿 openid，回来才能 JSAPI 下单（payer.openid 必填）
#   wechat_h5    → h5：h5_url 只有 5 分钟有效，客人在付款页点「打开微信付款」时才去要（官方：在用户实际发起支付的时点再下单）
DEFERRED_KIND: dict[str, str] = {"wechat_jsapi": "oauth", "wechat_h5": "h5"}
H5_URL_FRESH_SEC = 240  # h5_url 有效期 5 分钟（H5下单 4012791834），留 1 分钟余量：领到超过 4 分钟就重新要
_ALNUM = string.ascii_uppercase + string.digits

# 下单页的几句提示（字摘自 psyppt 官网的退款与售后、交付说明；数字从订单中枢设置来）。
# 我的建议：以后挪进订单中枢的设置（像 entry_texts 那样后台能改），见汇报。
NOTICES = (
    "这是按你的材料单独做的定制服务：开工前想撤单可以退款，开始制作后不支持仅退款；基础价含 {revisions} 轮修改。",
    "先交水印版：水印版交出后 {days} 天内没提修改、也没确认，系统自动确认收货，再发可编辑的 PPT 和讲稿。",
    "付款后马上拿到激活码：用它认领订单，再交材料。",
)
# 自有网页暂不收款（微信支付、支付宝商户号还没下来，SHOP_METHODS 里没有配好的真网关）时，下单页照常看价、选档，
# 「去付款」换成这句；店铺位置在后台「官网」设置里（小红书、闲鱼店铺链接，空着只显示文字）。配好真网关自动恢复。
PLATFORM_HINT = "现在请在小红书或闲鱼下单，付款后会收到兑换码"
PLATFORM_NOTICE = "在小红书或闲鱼付款后，发货消息里有兑换码和兑换网址：用它认领订单，再交材料。"
# 下单前要勾的几项（和官网模块 app/website/consent.py 的 REQUIRED_CONSENTS 一一对上；本模块不 import website，
# 由 scripts/check.py 规矩 18 核对两边一致）。建单时交给节点 website.consent 校验并留痕，没勾全不建单
CONSENT_NODE = "website.consent"


# ---------------------------------------------------------------- 小工具

def ua_kind(ua: str) -> str:
    return net.ua_kind(ua)  # 跟登录同一个判断（挪到 app/core/net.py，12 号设计）


def to_fen(amount: str) -> int:
    try:
        return int((Decimal(str(amount)) * 100).to_integral_value())
    except (InvalidOperation, ValueError) as e:
        raise ValueError(f"金额不对：{amount}") from e


def new_trade_no(now: datetime, prefix: str = "PS") -> str:
    """商户订单号：PS + 北京时间 yyMMddHHmmss + 6 位随机，共 20 位（微信要 6–32 位字母数字）。"""
    return prefix + now.astimezone(BEIJING).strftime("%y%m%d%H%M%S") + "".join(secrets.choice(_ALNUM) for _ in range(6))


def _mask(ref: str) -> str:
    return ref if len(ref) <= 10 else ref[:4] + "…" + ref[-6:]


def _lock(db: Any, row: ShopCheckout) -> None:
    """占锁：先写一下这一行（SQLite 同一时刻只有一个写的），再重新读，看到的就是别人提交后的样子。"""
    db.execute(update(ShopCheckout).where(ShopCheckout.id == row.id).values(updated_at=utcnow()))
    db.refresh(row)


def _notify(call: NodeCall, text: str) -> None:
    run_node("notify.feishu", call, {"text": text[:2000], "link": "/admin/channels", "level": "urgent", "kind": "网页付款异常"})


def redeem_url(rt: Any, row: ShopCheckout) -> str:
    tpl = rt.settings.SHOP_REDEEM_URL or "/chat"
    if row.session_ref and tpl.rstrip("/") == "/chat":
        return f"/chat/{row.session_ref}"
    return tpl.replace("{code}", row.code)


def web_out(rt: Any, row: ShopCheckout, **extra: Any) -> WebOut:
    show_code = row.code and row.status in ("paid", "part_refunded") and row.create_exit in ("created", "exists")
    pay = {"kind": row.pay_kind, "payload": {k: v for k, v in (row.pay_payload or {}).items() if k != "simulated"},
           "method": row.method, "method_label": METHOD_LABELS.get(row.method, row.method),
           "simulated": bool((row.pay_payload or {}).get("simulated"))}
    return WebOut(order_id=row.order_id if show_code else None, code=row.code if show_code else "", view_token=row.view_token,
                  status=row.status, total_fen=row.amount_fen, expires_at=row.expires_at, paid_at=row.paid_at,
                  pay=pay if row.status == "pending" else {**pay, "payload": {}}, **extra)


# ---------------------------------------------------------------- 价目、付款方式、报价

def _placed(row: ShopCheckout) -> bool:
    """这张待付款单在网关那边下过单没有（微信里还没授权、手机浏览器还没点「打开微信付款」的没下过，查单关单都不用去）。"""
    return row.pay_kind not in DEFERRED_KIND.values()


def oauth_ready(rt: Any, node: str) -> bool:
    """微信里付款能不能用：服务号网页授权要 AppSecret（WECHAT_MP_APPSECRET_FILE 优先，再看 WECHAT_MP_APPSECRET）。
    没配就整块关掉：下单页不出「微信支付」、/api/shop/wx/* 回 404，不报错。假网关也要配一个（随便什么字），开关跟线上一样。"""
    return bool(rt.settings.mp_appsecret()) and (node == "pay.fake" or bool(rt.settings.WECHATPAY_APPID))


def _node_ready(rt: Any, node: str) -> bool:
    """这个支付节点现在能不能用：登记了、配置齐了；假网关只在 SHOP_FAKE_PAY 且不是生产时算数。"""
    s = rt.settings
    if not has_handler(node):
        return False
    if node == "pay.fake":
        return bool(s.SHOP_FAKE_PAY) and getattr(rt, "app_env", "dev") != "prod"
    if node == "pay.wechat":
        return not s.wechat_missing()
    if node == "pay.alipay":
        return not s.alipay_missing()
    return True


def available_methods(rt: Any, kind: str) -> list[dict[str, str]]:
    """按客人在哪打开（电脑 / 手机 / 微信里）给开着的付款方式。微信里不出支付宝、手机上不出 Native（设计第五节第 3 条）。"""
    out = []
    for method, node in rt.settings.methods().items():
        if kind not in METHOD_UA[method] or not _node_ready(rt, node):
            continue
        if method == "wechat_jsapi" and not oauth_ready(rt, node):
            continue
        out.append({"method": method, "label": METHOD_LABELS[method], "node": node})
    return out


def jsapi_node(rt: Any) -> str | None:
    """微信里付款（JSAPI）用哪个支付节点；没开（SHOP_METHODS 里没有、商户配置不齐、没配 AppSecret）= None。"""
    node = rt.settings.methods().get("wechat_jsapi")
    return node if node and _node_ready(rt, node) and oauth_ready(rt, node) else None


def pay_mode(rt: Any) -> str:
    """online：至少有一种付款方式配好了（不看设备）；platforms：一种都没有 = 自有网页暂不收款，引导去小红书、闲鱼下单。"""
    return "online" if any(_node_ready(rt, node) for node in rt.settings.methods().values()) else "platforms"


def open_in_wechat(rt: Any, kind: str, methods: list[dict[str, str]]) -> bool:
    """手机浏览器里没有能用的付款方式（微信 H5 还没开），但微信里能付（JSAPI 开了）：引导「复制网址到微信里打开」。"""
    return kind == "mobile" and not methods and any(m["method"] == "wechat_jsapi" for m in available_methods(rt, "wechat"))


def methods_hint(rt: Any, kind: str, methods: list[dict[str, str]]) -> str:
    if methods:
        return ""
    if kind == "wechat":
        if any(m["method"].startswith("alipay") for m in available_methods(rt, "mobile")):
            return "在微信里还不能直接付款：点右上角，在浏览器里打开用支付宝付；或者用电脑打开这个网址扫码付。"
        return "在微信里还不能直接付款：用电脑打开这个网址扫码付。"
    if kind == "mobile":
        if open_in_wechat(rt, kind, methods):
            return "手机浏览器里还不能直接付：复制这个网址，到微信里打开就能付（发给自己或文件传输助手，点开就行）。"
        return "手机上暂时还不能付款：用电脑打开这个网址扫码付。"
    return "付款还没开通，可以先看价格。"


def _money(d: Any) -> str | None:
    return pricing.fmt_money(d) if d is not None else None


def catalog(call: NodeCall, rt: Any, ua: str) -> dict[str, Any]:
    cat = run_node("sku.catalog", call, {}).output
    kind = ua_kind(ua)
    methods = available_methods(rt, kind)
    mode = pay_mode(rt)
    notices = [n.format(days=cat.auto_confirm_days, revisions=cat.revisions_included) for n in NOTICES]
    if mode == "platforms":
        notices[-1] = PLATFORM_NOTICE
    return {
        "enabled": bool(rt.settings.SHOP_ENABLED),
        "tiers": [{"key": ct.key, "name": ct.name, "min_minutes": ct.min_minutes, "max_minutes": ct.max_minutes,
                   "max_pages": ct.max_pages, "std_hours": ct.std_hours, "rush_hours": ct.rush_hours, "rush": ct.rush,
                   "prices": {k: _money(v) for k, v in ct.prices.items()}} for ct in cat.tiers],  # 价目节点给的时限已含余量
        "bands": [{"key": b["key"], "name": b["name"], "max_papers": b["max_papers"]} for b in cat.bands],
        "addons": [{"key": a["key"], "name": a["name"], "price": _money(a["price"]), "note": a.get("note") or ""}
                   for a in cat.addons],
        "find_refs_extra_hours": cat.find_refs_extra_hours,
        "revisions_included": cat.revisions_included,
        "auto_confirm_days": cat.auto_confirm_days,
        "page_rule_text": cat.page_rule_text,
        "materials": cat.materials,  # 下单前准备好这些（订单中枢设置里的资料清单）
        "methods": [{"method": m["method"], "label": m["label"]} for m in methods],
        "ua_kind": kind,
        "hint": PLATFORM_HINT if mode == "platforms" else methods_hint(rt, kind, methods),
        "open_in_wechat": mode == "online" and open_in_wechat(rt, kind, methods),
        "pay_mode": mode,
        "notices": notices,
        "site_url": rt.settings.SHOP_SITE_URL,
        "price_hash": cat.price_hash,
    }


def quote_for(call: NodeCall, *, tier: str, band: str, rush: bool, find_refs: bool, extra_revisions: int) -> tuple[Any, str]:
    """按下单页选的档位报价（sku.quote）。选的组合报不出来、被升档、加急不能加，都算报不了。"""
    cat = run_node("sku.catalog", call, {}).output
    t = next((x for x in cat.tiers if x.key == tier), None)
    if find_refs and cat.bands:
        band = cat.bands[0]["key"]  # 帮我找文献按 1 篇算，不叠多篇（Edison 11-21）
    b = next((x for x in cat.bands if x["key"] == band), None)
    if t is None or b is None:
        return None, "没有这一档"
    if t.prices.get(band) is None:
        return None, f"{t.name}档不开放{b['name']}"
    r = run_node("sku.quote", call, {"minutes": t.max_minutes, "papers": b["max_papers"], "rush": rush,
                                     "find_refs": find_refs, "extra_revisions": extra_revisions})
    q = r.output
    if r.exit != "ok" or q is None:
        return None, r.detail or "报不出价"
    if q.sku != f"{tier}-{band}":
        return None, "这一档和篇数的组合现在不卖"
    if rush and not any(a["key"] == "rush" for a in q.addons):
        return None, f"不能加急：{q.rush_why or '这一档不开放加急'}"
    return q, ""


def quote_view(q: Any) -> dict[str, Any]:
    return {"sku": q.sku, "sku_name": q.sku_name, "base_price": q.base_price, "addons": q.addons, "total": q.total,
            "total_fen": to_fen(q.total), "hours": q.hours, "max_pages": q.max_pages, "rush_ok": q.rush_ok,
            "rush_why": q.rush_why, "earliest_start": q.earliest_start, "eta_date": q.eta_date, "queue_full": q.queue_full,
            "notes": q.notes}


def _addon_keys(q: Any, extra_revisions: int, find_refs: bool) -> list[str]:
    keys = [a["key"] for a in q.addons if a["key"] in ("rush", "find_refs")]
    if find_refs and "find_refs" not in keys:
        keys.append("find_refs")
    return keys + ["revision"] * extra_revisions


# ---------------------------------------------------------------- 下单

def record_consent(call: NodeCall, req: WebCheckout, view_token: str) -> str:
    """交给节点 website.consent 校验三项都勾了并记一条事件（挂在这张付款单上）。返回空 = 过了；否则是给客人看的原因。
    官网模块没登记（节点不在）也不建单：宁可下不了单，不能没有同意记录就收钱。"""
    if not has_handler(CONSENT_NODE):
        return "下单前的确认现在记不下来，暂时不能下单，过一会儿再试"
    try:
        r = run_node(CONSENT_NODE, call, {
            "checkout_token": view_token, "items": list(req.consents), "terms_version": req.terms_version,
            "privacy_version": req.privacy_version, "ip": req.client_ip[:64], "ua": req.ua[:300]})
    except NodeError:  # 协议版本号这类格式不对
        return "下单前的确认信息不完整，刷新页面再勾一次"
    return "" if r.exit == "ok" else (r.detail or "三项确认都勾上才能付款")


def create_checkout(call: NodeCall, rt: Any, req: WebCheckout) -> NodeResult:
    s = rt.settings
    db = call.db
    if not s.SHOP_ENABLED:
        return NodeResult(exit="pay_unavailable", output=WebOut(why="暂停接单"), detail="暂停接单，过一阵再来")
    kind = ua_kind(req.ua)
    methods = {m["method"]: m for m in available_methods(rt, kind)}
    if req.method not in methods:
        return NodeResult(exit="pay_unavailable", output=WebOut(why=methods_hint(rt, kind, list(methods.values()))),
                          detail="这种付款方式现在用不了，换一种")
    q, why = quote_for(call, tier=req.tier, band=req.band, rush=req.rush, find_refs=req.find_refs,
                       extra_revisions=req.extra_revisions)
    if q is None:
        return NodeResult(exit="quote_rejected", output=WebOut(why=why), detail=why)
    if q.queue_full:
        why = "往后几天的名额都排满了，暂时不能下单，过一两天再来"
        return NodeResult(exit="quote_rejected", output=WebOut(why=why), detail=why)
    now = utcnow()
    node = methods[req.method]["node"]
    view_token, trade_no = secrets.token_urlsafe(24), new_trade_no(now)
    # 三项确认没勾全不建单（08 官网整合第四节；出境要「单独同意」，个人信息保护法第三十九条）。
    # 校验和留痕都在节点 website.consent 里，跟建单同一个事务：后面任何一步失败回滚，留痕也一起没
    why = record_consent(call, req, view_token)
    if why:
        return NodeResult(exit="consent_missing", output=WebOut(why=why), detail=why)
    amount = to_fen(q.total)
    subject = f"{s.SHOP_SUBJECT} · {q.sku_name}"
    expires = now + timedelta(minutes=s.SHOP_CHECKOUT_TTL_MIN)
    deferred = DEFERRED_KIND.get(req.method)
    if deferred:
        # 微信里（先去网页授权）、手机浏览器（点了才要 h5_url）：先只建待付款单，网关晚一步再下单
        out = PayOut(out_trade_no=trade_no, kind="", simulated=node == "pay.fake",
                     payload={"url": f"/api/shop/wx/oauth?t={view_token}"} if deferred == "oauth" else {})
        pay_kind = deferred
    else:
        # 先去网关下单（联网，不拿锁），再建待付款单
        r = run_node(node, call, PayCreate(out_trade_no=trade_no, amount_fen=amount, subject=subject, method=req.method,
                                           client_ip=req.client_ip, expires_at=expires, return_url=_pay_page(call, view_token)))
        if r.exit != "created" or r.output is None:
            record_event(db, "shop.checkout_failed", f"trade:{trade_no}", {"node": node, "exit": r.exit, "why": r.detail, "by": call.by})
            return NodeResult(exit="pay_unavailable" if r.exit == "unavailable" else "fail",
                              output=WebOut(why=r.detail), detail=f"付款单没开成：{r.detail}")
        out, pay_kind = r.output, r.output.kind
    row = ShopCheckout(view_token=view_token, out_trade_no=trade_no, pay_node=node, method=req.method, sku=q.sku,
                       addons=_addon_keys(q, req.extra_revisions, req.find_refs), quote=q.model_dump(mode="json"),
                       amount_fen=amount, subject=subject, status="pending", pay_kind=pay_kind,
                       pay_payload={**out.payload, "simulated": out.simulated}, session_ref=req.session_ref,
                       source=req.source, client_ip=req.client_ip[:64], ua_kind=kind, expires_at=expires,
                       created_at=now, updated_at=now)
    db.add(row)
    db.flush()
    record_event(db, "shop.checkout_created", f"checkout:{row.id}", {
        "out_trade_no": trade_no, "sku": q.sku, "addons": row.addons, "amount_fen": amount, "method": req.method,
        "node": node, "ua_kind": kind, "source": req.source, "deferred": deferred or "", "by": call.by})
    return NodeResult(exit="ok", output=web_out(rt, row))


def _pay_page(call: NodeCall, view_token: str) -> str:
    return f"{call.ctx.public_base_url.rstrip('/')}/order/pay/{view_token}"


# ---------------------------------------------------------------- 付款成功 → 建单

def _copy_consent(db: Any, row: ShopCheckout) -> None:
    """建单时勾的同意（挂在付款单上）抄一份到订单上：需求确认卡就不用再勾一遍，后台代确认也认（09 需求引导）。"""
    if not row.order_id or list_events(db, subject=f"order:{row.order_id}", type="website.consent", limit=1):
        return
    got = list_events(db, subject=f"checkout:{row.view_token}", type="website.consent", limit=1)
    if got:
        record_event(db, "website.consent", f"order:{row.order_id}", {**got[0].content, "from": f"checkout:{row.id}"})


def _apply_paid(call: NodeCall, rt: Any, row: ShopCheckout, out: PayOut, *, via: str) -> str:
    """付款成功（通知或查单）：核金额和商户号 → 订单中枢 order.create → 记下单和码。调之前要先占锁。"""
    db = call.db
    if row.create_exit in ("created", "exists"):
        return "exists"
    if not out.merchant_ok or out.amount_fen != row.amount_fen:
        why = "商户号 / AppID 对不上" if not out.merchant_ok else f"实付 {fen_to_amount(out.amount_fen)} 和应付 {fen_to_amount(row.amount_fen)} 对不上"
        record_event(db, "shop.pay_invalid", f"checkout:{row.id}", {"via": via, "why": why, "txn_id": out.txn_id, "by": call.by})
        _notify(call, f"自有网页单 {row.out_trade_no}：{why}，没建单。去后台「渠道与收款」看一眼，钱可能要退")
        return "invalid"
    now = utcnow()
    if row.status in ("pending", "closed"):
        row.status = "paid"
    row.gateway_txn_id, row.payer_ref, row.paid_fen = out.txn_id[:64], out.payer_ref[:128], out.amount_fen
    row.paid_at = out.paid_at or now
    paid = WebAdapter().parse_paid({"out_trade_no": row.out_trade_no, "sku": row.sku, "addons": row.addons,
                                    "payer_ref": row.payer_ref, "paid_at": row.paid_at, "amount_fen": row.paid_fen,
                                    "txn_id": row.gateway_txn_id, "source": row.source})
    r = run_node("order.create", call, paid)
    row.create_exit = r.exit
    if r.exit in ("created", "exists") and r.output is not None:
        row.order_id, row.code = r.output.order_id, r.output.code
        _copy_consent(db, row)
    elif r.exit == "blocked":
        _notify(call, f"自有网页单 {row.out_trade_no} 付了 {fen_to_amount(row.paid_fen)} 元，但这个付款人退款作废太多次，没发码："
                      "去后台「渠道与收款」把钱退了")
    else:
        _notify(call, f"自有网页单 {row.out_trade_no} 付了钱，建单失败：{r.detail}。去后台看一眼")
    record_event(db, "shop.pay_notified", f"checkout:{row.id}", {
        "via": via, "exit": r.exit, "order_id": row.order_id, "txn_id": row.gateway_txn_id,
        "payer": _mask(row.payer_ref), "amount_fen": row.paid_fen, "by": call.by})
    return r.exit


def _expire(call: NodeCall, rt: Any, row: ShopCheckout, now: datetime, *, query_first: bool = True) -> str:
    """付款页轮询或定时任务：去网关查一次（回调丢了靠这个补）；过期了还没付就去网关关单。返回待付款单现在的状态。"""
    placed = _placed(row)  # 网关那边没下过单的（微信里没授权完、手机浏览器没点付款）不用去查、去关
    r = run_node(row.pay_node, call, PayQuery(out_trade_no=row.out_trade_no)) if query_first and placed else None
    expired = now >= row.expires_at
    if placed and (r is None or r.exit != "paid") and expired:
        run_node(row.pay_node, call, PayClose(out_trade_no=row.out_trade_no))
    _lock(call.db, row)
    row.last_query_at = now
    if r is not None and r.exit == "paid" and r.output is not None and row.status in ("pending", "closed"):
        _apply_paid(call, rt, row, r.output, via="query")
    elif row.status == "pending" and (expired or (r is not None and r.exit == "closed")):
        row.status, row.closed_at = "closed", now
        record_event(call.db, "shop.checkout_closed", f"checkout:{row.id}", {"why": "过期没付" if expired else "网关说已关闭", "by": call.by})
    return row.status


def poll(call: NodeCall, rt: Any, token: str, now: datetime | None = None) -> NodeResult:
    row = call.db.scalar(select(ShopCheckout).where(ShopCheckout.view_token == token))
    if row is None:
        return NodeResult(exit="fail", output=WebOut(why="没有这个付款单"), detail="没有这个付款单")
    now = now or utcnow()
    if row.status == "pending":
        due = row.last_query_at is None or (now - row.last_query_at).total_seconds() >= rt.settings.SHOP_QUERY_MIN_INTERVAL_SEC
        if (due and _placed(row)) or now >= row.expires_at:
            _expire(call, rt, row, now)
    out = web_out(rt, row, why=CHECKOUT_STATUS_LABELS.get(row.status, row.status))
    if row.status == "pending":
        return NodeResult(exit="waiting", output=out)
    if row.status == "closed":
        return NodeResult(exit="closed", output=out)
    if row.create_exit == "blocked":
        return NodeResult(exit="blocked", output=out, detail="付了，但这个付款人退款作废太多次，没发码；负责人会退款")
    if row.create_exit not in ("created", "exists"):
        return NodeResult(exit="fail", output=out, detail="付了，建单出了问题；负责人已经收到通知，会尽快处理")
    return NodeResult(exit="ok", output=out)


# ---------------------------------------------------------------- 手机上的微信付款：微信里（JSAPI）、手机浏览器（H5）

def _row(call: NodeCall, token: str, method: str) -> ShopCheckout | None:
    row = call.db.scalar(select(ShopCheckout).where(ShopCheckout.view_token == token))
    return row if row is not None and row.method == method else None


def _settled(call: NodeCall, rt: Any, row: ShopCheckout, now: datetime) -> NodeResult | None:
    """不用再去网关下单的情况：已经付了 / 关了 / 过期了（顺手关掉）。返回 None = 还在等付款、没过期。"""
    if row.status == "pending" and now >= row.expires_at:
        _expire(call, rt, row, now)
    if row.status == "pending":
        return None
    return NodeResult(exit="closed" if row.status == "closed" else "ok", output=web_out(rt, row))


def wx_start(call: NodeCall, rt: Any, req: WebWxStart, now: datetime | None = None) -> NodeResult:
    """微信里付款，要不要先去网页授权：还没拿到调起参数的 → need_openid；已经拿到了（刷新、按了返回）→ ok，直接回付款页。"""
    row = _row(call, req.view_token, "wechat_jsapi")
    if row is None:
        return NodeResult(exit="fail", output=WebOut(why="没有这个付款单"), detail="没有这个付款单")
    done = _settled(call, rt, row, now or utcnow())
    if done is not None:
        return done
    if row.pay_kind == "jsapi":
        return NodeResult(exit="ok", output=web_out(rt, row))
    return NodeResult(exit="need_openid", output=web_out(rt, row))


def jsapi_prepare(call: NodeCall, rt: Any, req: WebJsapiPrepare, now: datetime | None = None) -> NodeResult:
    """网页授权回来了：用 openid 去 JSAPI 下单，把调起支付的参数记在待付款单上（openid 本身不记）。
    已经下过的不再下（同一个 code 只能换一次 openid，官方易错点要求「按业务单据缓存，避免重复换取」，换之前路由先问过 wx_start）。"""
    row = _row(call, req.view_token, "wechat_jsapi")
    if row is None:
        return NodeResult(exit="fail", output=WebOut(why="没有这个付款单"), detail="没有这个付款单")
    done = _settled(call, rt, row, now or utcnow())
    if done is not None:
        return done
    if row.pay_kind == "jsapi":
        return NodeResult(exit="ok", output=web_out(rt, row))
    # 去网关下单（联网，不拿锁）：金额、商品名、过期时间都用待付款单上记的，跟建单时一模一样
    r = run_node(row.pay_node, call, PayCreate(out_trade_no=row.out_trade_no, amount_fen=row.amount_fen, subject=row.subject,
                                               method=row.method, client_ip=row.client_ip, openid=req.openid,
                                               expires_at=row.expires_at, return_url=_pay_page(call, row.view_token)))
    if r.exit != "created" or r.output is None:
        record_event(call.db, "shop.checkout_failed", f"checkout:{row.id}", {"node": row.pay_node, "exit": r.exit, "why": r.detail,
                                                                            "step": "jsapi", "by": call.by})
        return NodeResult(exit="fail", output=web_out(rt, row, why=r.detail), detail=f"微信那边没下成单：{r.detail}")
    _lock(call.db, row)
    if row.status == "pending" and row.pay_kind == "oauth":  # 两个回调同时到：先到的记上，后到的不覆盖
        row.pay_kind, row.pay_payload = r.output.kind, {**r.output.payload, "simulated": r.output.simulated}
        record_event(call.db, "shop.jsapi_prepared", f"checkout:{row.id}", {"node": row.pay_node, "by": call.by})
    return NodeResult(exit="ok", output=web_out(rt, row))


def _issued_at(payload: dict[str, Any]) -> datetime | None:
    try:
        return datetime.fromisoformat(str(payload.get("issued_at") or ""))
    except ValueError:
        return None


def repay(call: NodeCall, rt: Any, req: WebRepay, now: datetime | None = None) -> NodeResult:
    """手机浏览器点「打开微信付款」：给一个新鲜的 h5_url（领到不到 4 分钟的直接给；第一次或过了就去 H5 下单）。
    再次下单用同一个商户订单号和原来的参数（官方：「超过有效期须使用原下单参数重新请求下单接口获取新的 h5_url」）；
    第一次下单用客人现在的 IP（payer_client_ip 要和调起支付时的客户端 IP 一致）。"""
    row = _row(call, req.view_token, "wechat_h5")
    if row is None:
        return NodeResult(exit="fail", output=WebOut(why="没有这个付款单"), detail="没有这个付款单")
    now = now or utcnow()
    done = _settled(call, rt, row, now)
    if done is not None:
        return done
    issued = _issued_at(row.pay_payload or {})
    if _placed(row) and issued is not None and (now - issued).total_seconds() < H5_URL_FRESH_SEC:
        return NodeResult(exit="ok", output=web_out(rt, row))
    again = _placed(row)
    ip = row.client_ip if again else (req.client_ip or row.client_ip)
    r = run_node(row.pay_node, call, PayCreate(out_trade_no=row.out_trade_no, amount_fen=row.amount_fen, subject=row.subject,
                                               method=row.method, client_ip=ip, expires_at=row.expires_at,
                                               return_url=_pay_page(call, row.view_token)))
    if r.exit != "created" or r.output is None:
        record_event(call.db, "shop.checkout_failed", f"checkout:{row.id}", {"node": row.pay_node, "exit": r.exit, "why": r.detail,
                                                                            "step": "h5", "by": call.by})
        return NodeResult(exit="fail", output=web_out(rt, row, why=r.detail), detail=f"微信付款链接没要到：{r.detail}")
    _lock(call.db, row)
    if row.status == "pending":
        row.pay_kind, row.pay_payload = r.output.kind, {**r.output.payload, "simulated": r.output.simulated}
        row.client_ip = ip[:64]
        record_event(call.db, "shop.h5_url_issued", f"checkout:{row.id}", {"node": row.pay_node, "again": again, "by": call.by})
    return NodeResult(exit="ok", output=web_out(rt, row))


# ---------------------------------------------------------------- 网关通知

def _remember_bad(call: NodeCall, pay_node: str, raw: bytes, exit_: str, why: str) -> None:
    key = f"{pay_node}:bad:{hashlib.sha256(raw).hexdigest()[:40]}"
    if call.db.scalar(select(ShopNotification.id).where(ShopNotification.dedupe_key == key)) is None:
        call.db.add(ShopNotification(pay_node=pay_node, kind="unknown", dedupe_key=key, verified=False, result=exit_, error=why[:500]))
    record_event(call.db, "shop.pay_invalid", f"notify:{pay_node}", {"exit": exit_, "why": why[:200], "by": call.by})


def handle_notify(call: NodeCall, rt: Any, req: WebNotify) -> NodeResult:
    db = call.db
    r = run_node(req.pay_node, call, PayNotify(headers=req.headers, raw=req.raw))
    out = r.output or PayOut(ack="fail", ack_status=500)
    if r.exit in ("invalid", "unavailable", "fail"):
        _remember_bad(call, req.pay_node, req.raw, r.exit, r.detail)
        return NodeResult(exit="invalid", output=WebOut(ack=out.ack, ack_status=out.ack_status, why=r.detail), detail=r.detail)
    if r.exit in ("refund_ok", "refund_failed"):
        if out.dedupe_key and db.scalar(select(ShopNotification.id).where(ShopNotification.dedupe_key == out.dedupe_key)):
            return NodeResult(exit="exists", output=WebOut(ack=out.ack, ack_status=out.ack_status))
        db.add(ShopNotification(pay_node=req.pay_node, kind="refund", dedupe_key=out.dedupe_key or secrets.token_hex(16),
                                verified=True, out_trade_no=out.out_trade_no[:32],
                                payload={"out_refund_no": out.out_refund_no, "refund_id": out.refund_id}, result=r.exit))
        ref = db.scalar(select(ShopRefund).where(ShopRefund.out_refund_no == out.out_refund_no))
        row = db.get(ShopCheckout, ref.checkout_id) if ref is not None else None
        if ref is not None and row is not None and ref.status == "processing":
            _lock(db, row)
            finish_refund(call, rt, row, ref, ok=r.exit == "refund_ok", refund_id=out.refund_id)
        return NodeResult(exit="ok", output=WebOut(ack=out.ack, ack_status=out.ack_status))
    if r.exit != "paid":
        return NodeResult(exit="ok", output=WebOut(ack=out.ack, ack_status=out.ack_status, why=r.detail))

    # 付款通知：先记一笔（dedupe_key 唯一），这一下同时占了锁
    old = db.scalar(select(ShopNotification).where(ShopNotification.dedupe_key == out.dedupe_key))
    if old is not None and old.result != "invalid":
        return NodeResult(exit="exists", output=WebOut(ack=out.ack, ack_status=out.ack_status, dedupe_key=out.dedupe_key))
    note = old or ShopNotification(pay_node=req.pay_node, kind="pay", dedupe_key=out.dedupe_key, verified=True,
                                   out_trade_no=out.out_trade_no[:32],
                                   payload={"txn_id": out.txn_id, "amount_fen": out.amount_fen, "payer": _mask(out.payer_ref),
                                            "merchant_ok": out.merchant_ok})
    if old is None:
        db.add(note)
        try:
            db.flush()
        except IntegrityError:
            db.rollback()  # 同一笔通知并发进来，另一个已经记下并处理了
            return NodeResult(exit="exists", output=WebOut(ack=out.ack, ack_status=out.ack_status, dedupe_key=out.dedupe_key))
    row = db.scalar(select(ShopCheckout).where(ShopCheckout.out_trade_no == out.out_trade_no))
    if row is None:
        note.result = "no_checkout"
        _notify(call, f"收到一笔付款通知，商户订单号 {out.out_trade_no} 在我们这里找不到，没建单。去后台看一眼")
        return NodeResult(exit="invalid", output=WebOut(ack=out.ack, ack_status=out.ack_status), detail="找不到这个付款单")
    _lock(db, row)
    exit_ = _apply_paid(call, rt, row, out, via="notify")
    note.result = exit_
    if exit_ == "invalid":  # 金额、商户号对不上：不建单，回失败让网关重发（同时已经通知负责人）
        fail_ack: dict[str, Any] | str = {"code": "FAIL", "message": "金额或商户号不对"} if isinstance(out.ack, str) and not out.ack else "fail"
        return NodeResult(exit="invalid", output=WebOut(ack=fail_ack, ack_status=500), detail="金额或商户号对不上")
    result = web_out(rt, row, ack=out.ack, ack_status=out.ack_status, dedupe_key=out.dedupe_key)
    if exit_ == "blocked":
        return NodeResult(exit="blocked", output=result, detail="付款人退款作废太多次，没发码")
    if exit_ not in ("created", "exists"):
        return NodeResult(exit="fail", output=result, detail="建单失败")
    return NodeResult(exit="ok" if exit_ == "created" else "exists", output=result)


# ---------------------------------------------------------------- 退款（只有后台）

def finish_refund(call: NodeCall, rt: Any, row: ShopCheckout, ref: ShopRefund, *, ok: bool, refund_id: str = "") -> None:
    if ref.status != "processing":
        return
    now = utcnow()
    ref.finished_at = now
    ref.gateway_refund_id = refund_id[:64] or ref.gateway_refund_id
    if not ok:
        ref.status = "closed"
        row.status = "part_refunded" if row.refunded_fen else "paid"
        record_event(call.db, "shop.refund_done", f"checkout:{row.id}", {"refund": ref.out_refund_no, "ok": False, "by": call.by})
        _notify(call, f"自有网页单 {row.out_trade_no} 的退款 {fen_to_amount(ref.amount_fen)} 元没退成，去后台看一眼")
        return
    ref.status = "success"
    row.refunded_fen += ref.amount_fen
    full = row.refunded_fen >= row.paid_fen
    row.status = "refunded" if full else "part_refunded"
    if full and row.order_id:
        v = run_node("order.void", call, {"order_id": row.order_id, "code_action": "void", "why": f"自有网页退款：{ref.reason}"[:200]})
        ref.void_result = "订单作废了，码作废" if v.exit == "ok" else f"钱退了，订单没作废：{v.detail}"[:200]
        if v.exit != "ok":
            _notify(call, f"自有网页单 {row.out_trade_no} 钱退了，但订单没作废（{v.detail}），去后台看一眼")
    elif not full:
        ref.void_result = "部分退款，订单不动"
    record_event(call.db, "shop.refund_done", f"checkout:{row.id}", {
        "refund": ref.out_refund_no, "ok": True, "amount_fen": ref.amount_fen, "full": full, "void": ref.void_result, "by": call.by})


def refund(call: NodeCall, rt: Any, req: WebRefund) -> NodeResult:
    db = call.db
    row = db.scalar(select(ShopCheckout).where(ShopCheckout.order_id == req.order_id).order_by(ShopCheckout.id.desc()))
    if row is None:
        return NodeResult(exit="fail", output=WebOut(), detail="这单不是在自有网页付款的（平台单去平台后台退款）")
    _lock(db, row)  # 先占锁再看状态：两个退款同时点，后到的看到「退款中」就不再退（原来先看后占锁，PG 下两个都能过）
    if row.status not in ("paid", "part_refunded"):
        return NodeResult(exit="fail", output=WebOut(), detail=f"这单现在是「{CHECKOUT_STATUS_LABELS.get(row.status, row.status)}」，不能再退")
    left = row.paid_fen - row.refunded_fen
    if req.amount_fen > left:
        return NodeResult(exit="fail", output=WebOut(), detail=f"最多还能退 {fen_to_amount(left)} 元")
    ref = ShopRefund(checkout_id=row.id, order_id=row.order_id, out_refund_no=new_trade_no(utcnow(), "RF"),
                     amount_fen=req.amount_fen, scope=req.scope, reason=req.reason, by=call.by, status="processing")
    db.add(ref)
    row.status = "refunding"
    record_event(db, "shop.refund_requested", f"checkout:{row.id}", {
        "order_id": row.order_id, "amount_fen": req.amount_fen, "scope": req.scope, "reason": req.reason, "by": call.by})
    db.commit()  # 先记下「退款中」再去退钱：进程中途挂了也有据可查，也不拿着锁等网络
    r = run_node(row.pay_node, call, PayRefund(out_trade_no=row.out_trade_no, out_refund_no=ref.out_refund_no,
                                               total_fen=row.paid_fen, refund_fen=req.amount_fen, reason=req.reason))
    _lock(db, row)
    db.refresh(ref)
    if r.exit == "refund_ok":
        finish_refund(call, rt, row, ref, ok=True, refund_id=r.output.refund_id if r.output else "")
        return NodeResult(exit="ok", output=web_out(rt, row, refund_id=ref.id))
    if r.exit == "refund_processing":
        ref.gateway_refund_id = (r.output.refund_id if r.output else "")[:64]
        return NodeResult(exit="waiting", output=web_out(rt, row, refund_id=ref.id), detail="网关在处理，稍后自动再查")
    ref.status, ref.finished_at = ("abnormal" if r.exit == "fail" else "closed"), utcnow()
    row.status = "part_refunded" if row.refunded_fen else "paid"
    record_event(db, "shop.refund_done", f"checkout:{row.id}", {"refund": ref.out_refund_no, "ok": False, "why": r.detail, "by": call.by})
    return NodeResult(exit="fail", output=web_out(rt, row, refund_id=ref.id), detail=f"没退成：{r.detail}")


# ---------------------------------------------------------------- 定时：关过期单、查退款

def sweep(call: NodeCall, rt: Any, now: datetime | None = None) -> NodeResult:
    db = call.db
    now = now or utcnow()
    closed = paid = refunds = 0
    rows = list(db.scalars(select(ShopCheckout).where(ShopCheckout.status == "pending", ShopCheckout.expires_at <= now)
                           .order_by(ShopCheckout.id).limit(50)))
    for row in rows:
        st = _expire(call, rt, row, now)
        closed += st == "closed"
        paid += st == "paid"
    pend = list(db.scalars(select(ShopRefund).where(ShopRefund.status == "processing",
                                                    ShopRefund.created_at <= now - timedelta(minutes=1)).limit(20)))
    for ref in pend:
        row = db.get(ShopCheckout, ref.checkout_id)
        if row is None:
            continue
        r = run_node(row.pay_node, call, PayRefundQuery(out_trade_no=row.out_trade_no, out_refund_no=ref.out_refund_no))
        if r.exit in ("refund_ok", "refund_failed"):
            _lock(db, row)
            db.refresh(ref)
            finish_refund(call, rt, row, ref, ok=r.exit == "refund_ok", refund_id=r.output.refund_id if r.output else "")
            refunds += 1
    return NodeResult(exit="ok", output=WebOut(swept={"closed": closed, "paid": paid, "refunds": refunds}))
