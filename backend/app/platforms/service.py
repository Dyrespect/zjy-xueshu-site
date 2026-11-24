"""平台渠道节点背后的实现：录单、买家填订单号、负责人核对、平台信号、「该看一眼」清单、商品对照。

收单段（设计第七节）：
- parse_paid（人工录单）：表单 → 适配器 parse_paid → order.create → 发货文案（模板在订单中枢设置）→ gate.platform_text
  → 适配器 write_delivery（人工渠道 = 交给负责人去贴）。
- verify_then_create（固定链接）：买家填订单号 → 待核对 → 负责人点通过 → 同上建单，码只在我们页面上给。
平台信号：「已完成」走 confirm.receipt（负责人点的算 edison 来源，各渠道都认）；申请退款、退款、退款关闭走 order.signal。
幂等：按（渠道, 平台订单号）去重，同一个订单号录两次、填两次都返回同一个结果。
注意：本文件的字符串会被 check.py 规矩 11 按红线词表扫——不写平台名，渠道名用档案里的 label。
"""

from __future__ import annotations

import re
import secrets
from datetime import timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.db import utcnow
from app.core.events import record_event
from app.core.nodes import NodeCall, NodeResult, run_node
from app.intake import pricing
from app.intake.platform_texts import delivery_text_for
from app.platforms import profiles
from app.platforms.adapters import get_adapter
from app.platforms.models import INBOX_EXIT_LABELS, PlatformsInbox, PlatformsProduct
from app.platforms.models_io import ManualForm, PlatformInbound, PlatformOut, PlatformSignalIn, PlatformVerify

ORDER_NO = re.compile(r"^[A-Za-z0-9-]{6,40}$")
REDEEM_URL = "/c/{code}"  # 拿到码以后去哪交：兑换页（模块 D）


def _key(platform: str, no: str) -> str:
    return f"{platform}:{no.strip()}"


def _notify(call: NodeCall, text: str) -> None:
    run_node("notify.feishu", call, {"text": text[:2000], "link": "/admin/channels", "level": "urgent", "kind": "平台订单"})


def _out(row: PlatformsInbox, **extra: Any) -> PlatformOut:
    return PlatformOut(inbox_id=row.id, order_id=row.order_id, code=row.code, text_for_edison=row.delivery_text,
                       verify_status=row.verify_status, dedupe_key=row.dedupe_key, **extra)


def _label(p: dict[str, Any]) -> str:
    return str(p.get("label") or "")


# ---------------------------------------------------------------- 建单 + 发货文案

def _deliver(call: NodeCall, platform: str, prof: dict[str, Any], row: PlatformsInbox) -> NodeResult:
    db = call.db
    adapter = get_adapter(platform, prof["adapter"])
    paid = adapter.parse_paid({"platform_order_id": row.platform_order_id, "sku": row.sku, "addons": row.addons,
                               "buyer_id": row.buyer_hint, "paid_amount": row.paid_amount, "raw_ref": f"inbox:{row.id}",
                               "source": platform, "flow_key": prof.get("flow_key", "paid_custom")})
    if paid is None:
        row.exit, row.error = "fail", "订单号或货号空着"
        return NodeResult(exit="fail", output=_out(row), detail=row.error)
    r = run_node("order.create", call, paid)
    if r.exit == "blocked":
        row.exit = "blocked"
        _notify(call, f"{_label(prof)}订单 {row.platform_order_id}：这个买家退款作废太多次，没发码。去平台主动退款（虚拟单有发货时限）")
        record_event(db, "platforms.blocked", f"inbox:{row.id}", {"platform": platform, "by": call.by})
        return NodeResult(exit="blocked", output=_out(row), detail="买家退款作废太多次，没发码，去平台退款")
    if r.exit not in ("created", "exists") or r.output is None:
        row.exit, row.error = "fail", r.detail[:500]
        return NodeResult(exit="fail", output=_out(row), detail=f"建单失败：{r.detail}")
    row.order_id, row.code = r.output.order_id, r.output.code
    text = delivery_text_for(db, row.code, call.ctx.public_base_url, prof.get("delivery_template", "code_and_url"))
    if prof.get("text_gate", True) and prof["mode"] != "verify_then_create":
        g = run_node("gate.platform_text", call, {"platform": platform, "text": text, "allow": [row.code]})
        if g.exit == "blocked":
            row.exit, row.error = "text_blocked", "、".join(g.output.hits if g.output else [])[:500]
            _notify(call, f"{_label(prof)}订单 {row.platform_order_id} 的发货文案过不了红线（{row.error}），没发。去设置里改发货模板")
            return NodeResult(exit="text_blocked", output=_out(row), detail=f"发货文案里有不许出现的字：{row.error}")
    d = adapter.write_delivery(row.platform_order_id, text)
    record_event(db, "platforms.ingested", f"inbox:{row.id}", {
        "platform": platform, "source": row.source, "order_id": row.order_id, "create": r.exit, "delivery": d.exit, "by": call.by})
    if d.exit == "manual":
        row.exit, row.delivery_text = "manual", d.text_for_edison
        return NodeResult(exit="manual", output=_out(row))
    if d.exit == "written":
        row.exit = "delivered"
        return NodeResult(exit="delivered", output=_out(row, redeem_url=REDEEM_URL.format(code=row.code)))
    row.exit, row.error = "fail", d.detail[:500]
    return NodeResult(exit="retry" if d.exit == "retry" else "fail", output=_out(row), detail=d.detail)


def _new_row(call: NodeCall, **kw: Any) -> tuple[PlatformsInbox | None, PlatformsInbox | None]:
    """建一条收件箱；同一个（渠道, 订单号）已经有了就返回（None, 已有的）。"""
    db = call.db
    old = db.scalar(select(PlatformsInbox).where(PlatformsInbox.dedupe_key == kw["dedupe_key"]))
    if old is not None:
        return None, old
    row = PlatformsInbox(by=call.by, **kw)
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        return None, db.scalar(select(PlatformsInbox).where(PlatformsInbox.dedupe_key == kw["dedupe_key"]))
    return row, None


# ---------------------------------------------------------------- 进来一单

def ingest(call: NodeCall, platform: str, req: PlatformInbound) -> NodeResult:
    prof = profiles.get(call.db, platform)
    if prof is None or not prof.get("enabled"):
        return NodeResult(exit="ignored", output=PlatformOut(why="这个渠道没开"), detail="这个渠道没开")
    if req.source in ("push", "tool"):
        adapter = get_adapter(platform, prof["adapter"])
        if not adapter.verify(req.headers, req.raw):
            return NodeResult(exit="invalid", output=PlatformOut(ack="fail"), detail="这个渠道现在没有推送（人工录单），或签名不对")
        return NodeResult(exit="ignored", output=PlatformOut(ack="success"), detail="推送收单还没接（P2）")
    if req.source == "buyer_claim":
        return _claim(call, platform, prof, req)
    return _manual(call, platform, prof, req)


def _manual(call: NodeCall, platform: str, prof: dict[str, Any], req: PlatformInbound) -> NodeResult:
    db = call.db
    if prof["mode"] == "verify_then_create":
        return NodeResult(exit="ignored", output=PlatformOut(), detail="这个渠道现在用固定链接收单：买家自己填订单号，你在后台核对")
    try:
        form = ManualForm.model_validate(req.form)
    except ValidationError as e:
        return NodeResult(exit="invalid", output=PlatformOut(), detail=f"表单不对：{e.errors()[0].get('msg', '')}")
    product = db.get(PlatformsProduct, form.product_id) if form.product_id else None
    if form.product_id and (product is None or product.platform != platform):
        return NodeResult(exit="invalid", output=PlatformOut(), detail="这个商品不是这个渠道的")
    sku = product.sku if product else form.sku
    addons = list(product.addons) if product else form.addons
    if not sku:
        return NodeResult(exit="invalid", output=PlatformOut(), detail="选一个商品，或直接选货号")
    no = form.platform_order_id.strip()
    row, old = _new_row(call, platform=platform, source="manual", dedupe_key=_key(platform, no), platform_order_id=no,
                        product_id=product.id if product else None, sku=sku, addons=addons,
                        paid_amount=form.paid_amount or (product.listed_price if product else ""),
                        buyer_hint=form.buyer_hint, verified=True, payload=form.model_dump())
    if old is not None:
        if old.code or old.exit in ("pending_verify",):
            return NodeResult(exit="exists", output=_out(old), detail="这个订单号录过了，原样给你")
        row = old  # 上次出错（建单失败、文案被拦）：再来一次
    assert row is not None
    return _deliver(call, platform, prof, row)


def _claim(call: NodeCall, platform: str, prof: dict[str, Any], req: PlatformInbound) -> NodeResult:
    db = call.db
    if prof["mode"] != "verify_then_create":
        return NodeResult(exit="ignored", output=PlatformOut(why="这个链接现在不能用"), detail="这个渠道现在不用固定链接")
    token = str(req.form.get("product_token") or "")
    no = re.sub(r"\s+", "", str(req.form.get("platform_order_id") or ""))
    product = db.scalar(select(PlatformsProduct).where(PlatformsProduct.token == token, PlatformsProduct.active.is_(True),
                                                      PlatformsProduct.platform == platform)) if token else None
    if product is None:
        return NodeResult(exit="invalid", output=PlatformOut(why="链接不对"), detail="链接不对，或这个商品下架了")
    if not ORDER_NO.match(no):
        return NodeResult(exit="invalid", output=PlatformOut(why="订单号格式不对"), detail="订单号格式不对：只有字母、数字，6 到 40 位")
    row, old = _new_row(call, platform=platform, source="buyer_claim", dedupe_key=_key(platform, no), platform_order_id=no,
                        product_id=product.id, sku=product.sku, addons=list(product.addons), paid_amount=product.listed_price,
                        verified=False, verify_status="pending", claim_token=secrets.token_urlsafe(24), exit="pending_verify",
                        client_ip=req.client_ip[:64], payload={"product_token": token})
    if old is not None:  # 同一个订单号又填了一次：不把别人的码给出去，只说提交过了
        return NodeResult(exit="exists", output=PlatformOut(verify_status=old.verify_status or "ok",
                                                            why="这个订单号已经提交过了，在原来的页面看结果"),
                          detail="这个订单号已经提交过了")
    assert row is not None
    _notify(call, f"{_label(prof)}：有人在固定链接页填了订单号 {no}（{product.title or product.sku}），去后台「渠道与收款」核对")
    record_event(db, "platforms.pending_verify", f"inbox:{row.id}", {"platform": platform, "product_id": product.id, "by": call.by})
    return NodeResult(exit="pending_verify", output=_out(row, claim_token=row.claim_token))


def verify(call: NodeCall, platform: str, req: PlatformVerify) -> NodeResult:
    db = call.db
    prof = profiles.get(db, platform)
    row = db.get(PlatformsInbox, req.inbox_id)
    if prof is None or row is None or row.platform != platform or row.source != "buyer_claim":
        return NodeResult(exit="invalid", output=PlatformOut(), detail="没有这条待核对的")
    if row.verify_status != "pending":
        return NodeResult(exit="exists", output=_out(row), detail="已经核对过了")
    row.buyer_hint = req.buyer_hint or row.buyer_hint
    if not req.ok:
        row.verify_status, row.exit, row.error = "rejected", "rejected", req.note[:500]
        record_event(db, "platforms.rejected", f"inbox:{row.id}", {"platform": platform, "by": call.by})
        return NodeResult(exit="rejected", output=_out(row))
    row.verify_status, row.verified = "ok", True
    prof = {**prof, "mode": "verify_then_create"}
    return _deliver(call, platform, prof, row)


def claim_status(db: Any, claim_token: str) -> dict[str, Any] | None:
    row = db.scalar(select(PlatformsInbox).where(PlatformsInbox.claim_token == claim_token)) if claim_token else None
    if row is None:
        return None
    status = {"pending": "pending", "rejected": "rejected"}.get(row.verify_status, "ok" if row.code else "pending")
    if row.exit in ("blocked", "fail", "text_blocked"):
        status = "problem"
    return {"status": status, "code": row.code if status == "ok" else "", "redeem_url": REDEEM_URL.format(code=row.code) if status == "ok" else "",
            "platform_order_id": row.platform_order_id}


# ---------------------------------------------------------------- 平台信号（负责人点的）

def signal(call: NodeCall, platform: str, req: PlatformSignalIn) -> NodeResult:
    db = call.db
    row = db.scalar(select(PlatformsInbox).where(PlatformsInbox.dedupe_key == _key(platform, req.platform_order_id)))
    if row is None or row.order_id is None:
        return NodeResult(exit="invalid", output=PlatformOut(), detail="这个订单号没录过，或还没建单")
    now = utcnow()
    if req.kind == "completed":
        r = run_node("confirm.receipt", NodeCall(db, call.ctx, call.by, row.order_id), {
            "order_id": row.order_id, "source": "edison",
            "evidence": {"platform": platform, "platform_order_id": row.platform_order_id, "how": "负责人在平台后台看到已完成"}})
        ok = r.exit in ("completed", "recorded")
        stage = r.output.stage if r.output else ""
        if ok:
            row.completed_at = row.completed_at or now
    else:
        adapter = get_adapter(platform, profiles.get(db, platform)["adapter"])
        sig = adapter.parse_signal({"platform_order_id": row.platform_order_id, "kind": req.kind, "raw_ref": f"inbox:{row.id}"})
        r = run_node("order.signal", call, sig)
        ok = r.exit == "applied"
        stage = r.output.stage if r.output else ""
    row.signals = [*(row.signals or []), {"kind": req.kind, "at": now.isoformat(), "exit": r.exit, "by": call.by}]
    record_event(db, "platforms.signal", f"inbox:{row.id}", {"platform": platform, "kind": req.kind, "exit": r.exit, "by": call.by})
    if not ok:
        return NodeResult(exit="fail", output=_out(row, stage=stage), detail=r.detail or "订单中枢没接这个信号")
    return NodeResult(exit="signal_applied", output=_out(row, stage=stage, why=r.exit))


# ---------------------------------------------------------------- 后台：清单、商品

def _expected_price(cat: Any, sku: str, addons: list[str]) -> Decimal | None:
    p = pricing.parse_sku(sku)
    if p is None:
        return None
    price_of = {a["key"]: a["price"] for a in cat.addons}
    if p.kind == "addon":
        return price_of.get(p.addon)
    t = next((x for x in cat.tiers if x.key == p.tier), None)
    base = t.prices.get(p.band) if t else None
    if base is None:
        return None
    total = Decimal(base)
    for k in addons:
        if price_of.get(k) is None:
            return None
        total += price_of[k]
    return total


def due(call: NodeCall) -> list[dict[str, Any]]:
    """该看一眼：发货文案还没贴的、待核对的、付款很久还没点「平台已完成」的、没发出码的、商品标价和设置价对不上的。"""
    db = call.db
    profs = profiles.load(db)
    now = utcnow()
    items: list[dict[str, Any]] = []
    rows = list(db.scalars(select(PlatformsInbox).where(PlatformsInbox.completed_at.is_(None))
                           .order_by(PlatformsInbox.id.desc()).limit(300)))
    for row in rows:
        label = _label(profs.get(row.platform, {}))
        base = {"inbox_id": row.id, "platform": row.platform, "platform_label": label, "platform_order_id": row.platform_order_id,
                "order_id": row.order_id, "code": row.code, "at": row.created_at}
        if row.exit == "pending_verify":
            items.append({**base, "kind": "verify", "level": "high", "title": f"{label}订单 {row.platform_order_id} 等你核对",
                          "detail": "到平台订单里对上这个订单号再点通过"})
        elif row.exit in ("blocked", "fail", "text_blocked"):
            items.append({**base, "kind": "problem", "level": "high",
                          "title": f"{label}订单 {row.platform_order_id}：{INBOX_EXIT_LABELS.get(row.exit, row.exit)}",
                          "detail": row.error[:120]})
        elif row.exit == "manual" and row.pasted_at is None:
            items.append({**base, "kind": "paste", "level": "high", "title": f"{label}订单 {row.platform_order_id} 的发货文案还没贴",
                          "detail": "复制发货文案贴到平台，贴好点「贴好了」"})
        if row.order_id and row.exit in ("manual", "delivered"):
            hours = int(profs.get(row.platform, {}).get("remind_after_paid_hours") or 0)
            if hours and now - row.created_at >= timedelta(hours=hours):
                look = run_node("code.lookup", call, {"code": row.code}).output if row.code else None
                stage = look.stage if look else ""
                if stage not in ("completed", "delivered", "void"):
                    items.append({**base, "kind": "completion", "level": "mid", "stage": stage,
                                  "title": f"{label}订单 {row.platform_order_id} 录了 {hours} 小时还没点「平台已完成」",
                                  "detail": "去平台看一眼：买家确认收货了就点「平台已完成」，退款了点「已退款」"})
    cat = run_node("sku.catalog", call, {}).output
    for prod in db.scalars(select(PlatformsProduct).where(PlatformsProduct.active.is_(True))):
        want = _expected_price(cat, prod.sku, list(prod.addons or []))
        try:
            listed = Decimal(prod.listed_price) if prod.listed_price else None
        except InvalidOperation:
            listed = None
        if want is not None and listed is not None and listed != want:
            label = _label(profs.get(prod.platform, {}))
            items.append({"kind": "price", "level": "mid", "platform": prod.platform, "platform_label": label,
                          "title": f"{label}商品「{prod.title or prod.product_ref}」标价 {prod.listed_price}，设置里是 {pricing.fmt_money(want)}",
                          "detail": "去平台把价改成一样（或改设置）", "inbox_id": None, "order_id": None, "at": prod.created_at})
    return items


def new_product(db: Any, *, platform: str, product_ref: str, title: str, sku: str, addons: list[str], listed_price: str,
                note: str) -> PlatformsProduct:
    if platform not in profiles.PLATFORM_NODES:
        raise ValueError("没有这个渠道")
    p = pricing.parse_sku(sku)
    if p is None or p.kind == "legacy":
        raise ValueError(f"货号不对：{sku}")
    if listed_price:
        try:
            Decimal(listed_price)
        except InvalidOperation as e:
            raise ValueError("标价只写数字（两位小数）") from e
    row = PlatformsProduct(platform=platform, product_ref=product_ref.strip()[:64], title=title.strip()[:64], sku=sku,
                           addons=list(addons), listed_price=listed_price.strip()[:16], token=secrets.token_urlsafe(9)[:12],
                           note=note[:200])
    db.add(row)
    try:
        db.flush()
    except IntegrityError as e:
        db.rollback()
        raise ValueError("这个渠道已经登记过这个商品了") from e
    return row
