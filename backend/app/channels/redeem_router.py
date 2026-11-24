"""兑换网页的接口（/api/channels/redeem/*）：薄薄一层，事都在 entry.redeem_page 节点（app/channels/redeem.py）里。

- GET  /redeem            还没输入码：激活码从哪来、在哪买
- GET  /redeem/{code}     头 X-Web-Key（可选，这个浏览器存的聊天 key）→ 状态和按钮；同一 IP 每小时超了 429
- POST /redeem/{code}/web {key?} → {key, chat_path}；不能用 409 带原因；要先登录（12 号设计）没登录 401
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.channels import entries, limits, login, redeem
from app.channels.entry_config import load_entry_config
from app.channels.login_web import login_required
from app.channels.runtime import ChannelsRuntime, channels_dep
from app.core import access
from app.core.deps import client_ip, get_db, get_write_db
from app.core.nodes import NodeCall, run_node
from app.intake import flow

router = APIRouter(prefix="/redeem", tags=["channels"], dependencies=[Depends(access.by_token)])  # 激活码就是凭证


class ClaimWebIn(BaseModel):
    key: str | None = Field(default=None, max_length=64)


def _call(db: Session, rt: ChannelsRuntime) -> NodeCall:
    flow.ensure_nodes()
    return NodeCall(db, rt.intake.ctx, "customer")


def _available(db: Session, rt: ChannelsRuntime) -> list[str]:
    return [s.node_id for s in entries.all_specs() if s.available(db, rt)[0]]


def _limit(request: Request, db: Session) -> None:
    ip = client_ip(request)
    if not limits.limiter(request.app).hit("entry.redeem", ip, limit=load_entry_config(db).redeem_ip_hourly, window=3600):
        raise HTTPException(429, detail="查得太频繁了，过一会儿再试")


@router.get("", response_model=redeem.RedeemOut)
def meta(db: Session = Depends(get_db)) -> redeem.RedeemOut:
    return redeem.page_meta(db)


@router.get("/{code}", response_model=redeem.RedeemOut)
def view(code: str, request: Request, x_web_key: str | None = Header(default=None),
         rt: ChannelsRuntime = Depends(channels_dep), db: Session = Depends(get_write_db)) -> redeem.RedeemOut:
    _limit(request, db)
    me = access.current_customer(request, db)
    label = ""
    if me is not None:
        from app.channels.account import account_label

        label = account_label(me.method, login.phone_of(db, me.person_id))
    res = run_node("entry.redeem_page", _call(db, rt), {"action": "view", "code": code, "web_key": x_web_key,
                                                        "available": _available(db, rt), "person_id": me.person_id if me else None,
                                                        "login_required": login_required(request, rt, db), "login_label": label})
    db.commit()
    return res.output.view


@router.post("/{code}/web", response_model=redeem.ClaimWebOut)
def claim_web(code: str, body: ClaimWebIn, request: Request, rt: ChannelsRuntime = Depends(channels_dep),
              db: Session = Depends(get_db)) -> redeem.ClaimWebOut:
    _limit(request, db)
    me = access.current_customer(request, db)
    res = run_node("entry.redeem_page", _call(db, rt), {"action": "claim_web", "code": code, "web_key": body.key,
                                                        "person_id": me.person_id if me else None,
                                                        "login_required": login_required(request, rt, db)})
    if res.exit == "refused":
        db.rollback()
        raise HTTPException(res.output.refused_status, detail=res.output.refused)
    db.commit()
    return res.output.claimed
