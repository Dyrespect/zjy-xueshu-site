"""后台：需求卡（/api/admin/brief，整个要登录；docs/任务单/09_需求引导_方案.md）。

- 设置：题目、选项、示例句、推荐值、样张（缩略图地址、讲的哪篇论文）、几小时没确认提醒——都在这里改，前端不写死。
- 一单的需求卡：看客人点了什么、确认卡、什么时候谁确认的（客人点 / 负责人代确认和依据）、改动记录；
  负责人能改了再发给客人重新确认（入口发一句话 + 链接），也能代客人确认（必须写依据，事件里记明是代确认）。
- 不调模型；状态只由流程引擎走（确认了发 brief_confirmed 事件）。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.channels import brief_web
from app.core.deps import get_db
from app.core.events import list_events
from app.core.nodes import NodeCall
from app.intake import brief, flow
from app.intake.models import Order
from app.intake.runtime import get_runtime

router = APIRouter(prefix="/brief", tags=["admin"])

EVENT_LABELS = {
    "intake.brief_saved": "改了需求卡", "intake.brief_confirmed": "确认", "intake.brief_sent_back": "发回给客人重新确认",
    "intake.brief_reminded": "提醒了客人", "intake.brief_file": "传了文件", "intake.brief_file_removed": "删了文件",
}
WHO = {"customer": "客人", "edison": "你", "system": "系统"}


def _order(db: Session, oid: int) -> Order:
    o = db.get(Order, oid)
    if o is None:
        raise HTTPException(404, detail="没有这单")
    return o


def _admin_view(db: Session, request: Request, o: Order) -> dict[str, Any]:
    ctx = get_runtime(request.app).ctx
    v = brief.view(db, ctx, o)
    b = brief.get(db, o)
    hist = []
    for e in list_events(db, subject=f"order:{o.id}", limit=200):
        if e.type not in EVENT_LABELS:
            continue
        c = e.content or {}
        what = EVENT_LABELS[e.type]
        if e.type == "intake.brief_confirmed":
            what = "负责人代确认" if c.get("method") == "proxy" else "客人点了「对，开工」"
        hist.append({"at": e.created_at, "what": what, "who": WHO.get(str(c.get("by", "")), str(c.get("by", ""))),
                     "note": c.get("note") or c.get("name") or ""})
    ok, detail = brief.condition(db, o)
    v.update({
        "order_id": o.id, "url": brief.brief_url(ctx, o), "condition": {"ok": ok, "detail": detail},
        "card_text": b.card_text if b is not None and brief.is_confirmed(b) else "",
        "confirmed_by": b.confirmed_by if b is not None and brief.is_confirmed(b) else "",
        "history": hist[:30],
    })
    return v


@router.get("/settings")
def get_settings(db: Session = Depends(get_db)) -> dict[str, Any]:
    return {"settings": brief.load_settings(db).model_dump()}


class SettingsIn(BaseModel):
    settings: dict[str, Any]


@router.put("/settings")
def put_settings(body: SettingsIn, db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        s = brief.BriefSettings.model_validate(body.settings)
    except ValidationError as e:
        first = e.errors()[0]
        where = ".".join(str(x) for x in first.get("loc", ()))
        raise HTTPException(400, detail=f"设置不对（{where}）：{first.get('msg', '')}".replace("Value error, ", "")) from e
    brief.save_settings(db, s, by="edison")
    db.commit()
    return {"settings": brief.load_settings(db).model_dump()}


@router.get("/orders/{oid}")
def order_brief(oid: int, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _admin_view(db, request, _order(db, oid))


class EditIn(BaseModel):
    answers: dict[str, Any] = Field(default_factory=dict)
    send_back: bool = Field(default=True, description="改完发给客人重新确认（入口发一句话 + 链接）")
    note: str = Field(default="", max_length=200, description="发回时告诉客人改了什么")


@router.put("/orders/{oid}")
def edit(oid: int, body: EditIn, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    o = _order(db, oid)
    ctx = get_runtime(request.app).ctx
    flow.ensure_nodes()
    try:
        if body.send_back:
            brief.send_back(db, ctx, o, body.answers, note=body.note, by="edison")
            brief_web.notify(NodeCall(db, ctx, "edison", o.id), o, "brief_sent_back", note=body.note.strip())
        else:
            brief.save(db, ctx, o, body.answers, by="edison")
    except ValueError as e:
        db.rollback()
        raise HTTPException(409, detail=str(e)) from e
    db.commit()
    return _admin_view(db, request, o)


PROXY_NO_CONSENT = ("客人还没勾过「同意材料交给 AI 处理（含境外）」这几项，不能代确认：出境要本人单独同意。"
                    "把需求卡链接发给客人，让他在确认卡上勾一下、点「对，开工」")


class ProxyIn(BaseModel):
    note: str = Field(min_length=1, max_length=200, description="依据：客人在聊天里怎么说的")


@router.post("/orders/{oid}/confirm")
def proxy_confirm(oid: int, body: ProxyIn, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """代客人确认（客人在聊天里口头说「可以」）：事件里记 method=proxy、by=edison、依据。
    客人本人没勾过同意（材料交给 AI 处理含境外）的不许代确认：出境要本人单独同意，负责人不能代勾（个人信息保护法第三十九条）。"""
    o = _order(db, oid)
    if brief.editable(o) and not brief.has_consent(db, o):
        raise HTTPException(409, detail=PROXY_NO_CONSENT)
    ctx = get_runtime(request.app).ctx
    flow.ensure_nodes()
    try:
        brief.confirm(db, ctx, o, method="proxy", by="edison", note=body.note)
    except ValueError as e:
        db.rollback()
        raise HTTPException(409, detail=str(e)) from e
    db.commit()
    db.expire_all()
    return _admin_view(db, request, _order(db, oid))
