"""后台「入口」页（/api/admin/entry/*，自动要登录）：微信客服开关和状态、生成兑换用的客服链接、资料清单、
邮件服务状态、查一个客户（门、合并记录、偏好、两份摘要）。

- 微信客服默认关；凭证没配全或还没生成兑换用的客服链接时打不开（409 说清差什么）。
- 资料清单存在订单中枢的设置里（checklists，契约第二节第 6 条）；访客每天条数、欢迎语在「设置」页改，这里不重复。
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.channels import entries, mailer, memory
from app.channels.entry_config import EntryConfig, load_entry_config, save_entry_config
from app.channels.models import Contact
from app.channels.nodes.entry_wecom import REDEEM_SCENE
from app.channels.runtime import get_channels, wecom_configured
from app.channels.wecom_client import WecomError
from app.core.deps import get_db
from app.core.events import Event, record_event
from app.intake import pricing, service
from app.intake.config_store import Checklists, load_config, save_config
from app.intake.models import Customer

router = APIRouter(prefix="/entry", tags=["admin"])


def _wecom_state(db: Session, request: Request) -> dict[str, Any]:
    rt = get_channels(request.app)
    spec = entries.spec_by_node("entry.wecom")
    ok, why = spec.available(db, rt) if spec is not None else (False, "没登记微信客服入口")
    return {
        "configured": wecom_configured(rt.core),  # 只给有没有配，不给值
        "client_ready": rt.wecom is not None and rt.crypto is not None,
        "available": ok,
        "reason": why,
        "callback_path": "/api/channels/wecom/callback",
    }


def _out(db: Session, request: Request) -> dict[str, Any]:
    cfg = load_config(db)
    return {
        "config": load_entry_config(db).model_dump(mode="json"),
        "wecom": _wecom_state(db, request),
        "email": {"enabled": mailer.enabled(), "via": mailer.label()},
        "checklists": cfg.checklists.model_dump(mode="json"),
        "visitor": {"daily": cfg.visitor_daily_limit, "global_daily": cfg.visitor_global_daily_limit},
        "entries": [{"node_id": s.node_id, "label": s.label, "channel": s.channel} for s in entries.all_specs()],
    }


@router.get("")
def get_entry(request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    return _out(db, request)


class EntryIn(BaseModel):
    config: EntryConfig | None = None
    checklists: Checklists | None = None


@router.put("")
def put_entry(body: EntryIn, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    if body.config is not None:
        if body.config.wecom_enabled and not load_entry_config(db).wecom_enabled:
            rt = get_channels(request.app)
            if rt.wecom is None or rt.crypto is None:
                raise HTTPException(409, detail="企业微信凭证还没配全（.env 的 WECOM_CORPID、WECOM_KF_SECRET、WECOM_TOKEN、"
                                                "WECOM_AES_KEY、WECOM_OPEN_KFID），先配好再打开")
            if not body.config.wecom_links.get(REDEEM_SCENE):
                raise HTTPException(409, detail="还没生成兑换用的客服链接：先点「生成兑换用的客服链接」")
        save_entry_config(db, body.config)
    if body.checklists is not None:
        cfg = load_config(db)
        before_hash = pricing.price_hash(cfg)
        cfg.checklists = body.checklists
        save_config(db, cfg)
        record_event(db, "intake.config_changed", "", {"price_hash_before": before_hash, "price_hash_after": pricing.price_hash(cfg),
                                                       "fields": ["checklists"], "by": "edison"})
    db.commit()
    return _out(db, request)


class LinkIn(BaseModel):
    scene: str = Field(default=REDEEM_SCENE, min_length=1, max_length=32, pattern=r"^[0-9a-zA-Z_-]+$")


@router.post("/wecom-link")
async def wecom_link(body: LinkIn, request: Request, db: Session = Depends(get_db)) -> dict[str, Any]:
    """调 kf/add_contact_way 生成一条带 scene 的客服链接，原样存起来（兑换页在末尾拼 scene_param）。上线时点一次。"""
    rt = get_channels(request.app)
    if rt.wecom is None or not rt.open_kfid:
        raise HTTPException(503, detail="企业微信凭证还没配（WECOM_CORPID、WECOM_KF_SECRET、WECOM_OPEN_KFID）")
    try:
        url = await rt.wecom.add_contact_way(rt.open_kfid, body.scene)
    except WecomError as e:
        raise HTTPException(502, detail=f"企业微信返回：{e.errmsg}") from e
    cfg = load_entry_config(db)
    cfg.wecom_links = {**cfg.wecom_links, body.scene: url}
    save_entry_config(db, cfg)
    db.commit()
    return {"scene": body.scene, "url": url, **_out(db, request)}


def _mask(email: str) -> str:
    name, _, host = email.partition("@")
    return f"{name[:2]}***@{host}"


@router.get("/people/{customer_id}")
def person(customer_id: int, db: Session = Depends(get_db)) -> dict[str, Any]:
    c = db.get(Customer, customer_id)
    if c is None:
        raise HTTPException(404, detail="没有这个会话")
    p = memory.person_of(db, c.person_id)
    doors = memory.doors(db, p.id) if p is not None else [c]
    merges = []
    if p is not None:
        merges = [{"at": e.created_at, "content": e.content} for e in db.scalars(
            select(Event).where(Event.type.in_(("customer.merged", "customer.link_refused")),
                                Event.subject.in_([f"person:{p.id}", *[f"customer:{d.id}" for d in doors]]))
            .order_by(Event.id.desc()).limit(20))]
    return {
        "person_id": p.id if p else None,
        "doors": [{"id": d.id, "channel": d.channel, "name": service.display_name(d), "last_customer_msg_at": d.last_customer_msg_at}
                  for d in doors],
        "preferences": (p.preferences or {}) if p else {},
        "memory_brief": c.memory_brief, "handoff_brief": c.handoff_brief,
        "emails": [_mask(e) for e in db.scalars(select(Contact.email).where(Contact.person_id == p.id))] if p else [],
        "merges": merges,
    }
