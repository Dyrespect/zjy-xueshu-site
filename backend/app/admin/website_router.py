"""后台：官网（/api/admin/website，要登录；只有 Edison 用）。

- GET / PUT settings     页脚主体信息、联系电话、公安备案号、公开给搜索引擎、维护中……（空着的「待填」项标出来）
- GET       consents     最近的「下单前同意」记录（看客人勾了什么、哪一版协议）
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.deps import get_db
from app.core.events import list_events
from app.website.config import LAUNCH_FIELDS, load_config, save_config

router = APIRouter(prefix="/website", tags=["admin"])


def _view(cfg) -> dict[str, Any]:
    return {"config": cfg.model_dump(), "launch_fields": LAUNCH_FIELDS, "pending_launch": cfg.pending_launch()}


@router.get("/settings")
def get_settings(db: Session = Depends(get_db)) -> dict[str, Any]:
    return _view(load_config(db))


@router.put("/settings")
def put_settings(body: dict[str, Any], db: Session = Depends(get_db)) -> dict[str, Any]:
    try:
        cfg = save_config(db, body.get("config", body), by="edison")
    except (ValueError, ValidationError) as e:
        db.rollback()
        msg = e.errors()[0]["msg"] if isinstance(e, ValidationError) else str(e)
        raise HTTPException(422, detail=f"设置没存上：{msg.removeprefix('Value error, ')}") from e
    db.commit()
    return _view(cfg)


@router.get("/consents")
def consents(limit: int = 50, db: Session = Depends(get_db)) -> dict[str, Any]:
    rows = list_events(db, type="website.consent", limit=max(1, min(limit, 200)))
    # 付款单上的（自有网页下单时勾的）显示付款单令牌；订单上的（平台单在需求确认卡上勾的、或付款后抄过来的）显示「订单 #号」
    def where(ev: Any) -> str:
        if ev.subject.startswith("order:"):
            return f"订单 #{ev.subject.removeprefix('order:')}" + ("（下单时勾的，付款后抄过来）" if ev.content.get("from") else "（确认卡上勾的）")
        return ev.subject.removeprefix("checkout:")

    return {"rows": [{"at": ev.created_at.isoformat(), "checkout": where(ev),
                      "items": ev.content.get("items", []), "terms_version": ev.content.get("terms_version", ""),
                      "privacy_version": ev.content.get("privacy_version", ""), "ip": ev.content.get("ip", "")}
                     for ev in rows]}
