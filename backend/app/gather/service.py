"""聚人这条线的读写：分享码、领取、截图、网盘包、发链接的那段话。

导入本文件时把「一次领取」登记成能走流程的对象、把 flows/ 交给流程引擎（照 app/invoices/service.py 的做法）。
网盘链接只从 figure_packs 表读（后台贴），代码里没有任何网盘地址（check.py 规矩 17）。
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.gather.models import FLOW_KEY, FigurePack, FigureUnlock, PackGrant, UnlockEvidence
from app.gather.settings import GatherSettings
from app.gather.site import order_url
from app.intake import flow

flow.register_subject(flow.SubjectSpec("figure_unlock", FigureUnlock, None, stage_event="gather.stage", by_id="subject_id"))
flow.register_flow_dir(Path(__file__).parent / "flows")

CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ"  # 去掉 0 O 1 I L（和激活码同一套思路）
STAGE_SENT = "sent"


def new_share_code(db: Session) -> str:
    for _ in range(20):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
        if db.scalar(select(FigureUnlock.id).where(FigureUnlock.share_code == code)) is None:
            return code
    raise RuntimeError("分享码连撞 20 次，字符表或长度要加")


def by_code(db: Session, code: str) -> FigureUnlock | None:
    return db.scalar(select(FigureUnlock).where(FigureUnlock.share_code == (code or "").upper()[:12]))


def latest_for_visitor(db: Session, visitor: str) -> FigureUnlock | None:
    return db.scalar(select(FigureUnlock).where(FigureUnlock.visitor == visitor).order_by(FigureUnlock.id.desc()))


def save_evidence(db: Session, storage, unlock: FigureUnlock, data: bytes, ext: str, visitor: str) -> UnlockEvidence:
    sha = hashlib.sha256(data).hexdigest()
    rel = storage.save(data, folder=f"gather/evidence/{datetime.now().strftime('%Y-%m')}", filename=f"u{unlock.id}.{ext}")
    ev = UnlockEvidence(unlock_id=unlock.id, file=rel, sha256=sha, visitor=visitor)
    db.add(ev)
    db.flush()
    return ev


def active_pack(db: Session, tier: str) -> FigurePack | None:
    return db.scalar(select(FigurePack).where(FigurePack.tier == tier, FigurePack.active.is_(True))
                     .order_by(FigurePack.id.desc()))


def latest_grant(db: Session, unlock_id: int) -> PackGrant | None:
    return db.scalar(select(PackGrant).where(PackGrant.unlock_id == unlock_id).order_by(PackGrant.id.desc()))


def _fill(template: str, **values: Any) -> str:
    out = template
    for k, v in values.items():
        out = out.replace("{" + k + "}", str(v))
    return out


def pack_text(pack: FigurePack, cfg: dict[str, Any], gs: GatherSettings, *, figures_url: str = "") -> str:
    tpl = cfg["pack_text"] if pack.tier == "full" else cfg["gzh_reply_text"]
    return _fill(tpl, version=pack.version, count=pack.count or "", url=pack.url,
                 code_part=f" 提取码 {pack.extract_code}" if pack.extract_code else "", gzh=cfg["gzh_name"],
                 order_url=order_url(gs, "pack"), figures_url=figures_url or gs.SITE_FIGURES_URL or "")


def text_for_unlock(db: Session, unlock: FigureUnlock, cfg: dict[str, Any], gs: GatherSettings) -> tuple[str, str]:
    """发给这个人的那段话（含链接）。**只有流程走到「已发链接」才有**——没核验过、核验没过，永远拿不到链接。"""
    if unlock.stage != STAGE_SENT:
        return "", ""
    grant = latest_grant(db, unlock.id)
    pack = db.get(FigurePack, grant.pack_id) if grant is not None else None
    if pack is None:
        return "", ""
    current = active_pack(db, pack.tier)  # 后台换过链接（旧的被屏蔽）：给最新那一条
    if current is not None:
        pack = current
    return pack_text(pack, cfg, gs), pack.version


def start_unlock(db: Session, ctx: Any, visitor: str, src: str, ip: str, cfg: dict[str, Any]) -> tuple[FigureUnlock, bool]:
    """同一个访客只有一次领取（一个人只发一次全量；图库更新靠公众号通知，不用再转发）。"""
    existing = latest_for_visitor(db, visitor)
    if existing is not None:
        return existing, False
    u = FigureUnlock(visitor=visitor, share_code=new_share_code(db), src=src, tier="full",
                     verifiers=[cfg.get("verifier") or "screenshot_trust"], channel_user=visitor, ip=ip,
                     flow_key=FLOW_KEY)
    db.add(u)
    db.flush()
    flow.start(db, ctx, u, FLOW_KEY, by=f"visitor:{visitor[:12]}", why="点了「要全部图库？」")
    return u, True


def emit(db: Session, ctx: Any, unlock: FigureUnlock, event: str, *, by: str, why: str = "",
         data: dict[str, Any] | None = None) -> bool:
    return flow.emit(db, ctx, unlock, event, by=by, why=why, data=data)


def push(db: Session, ctx: Any, unlock: FigureUnlock, on: str, *, by: str, why: str) -> None:
    flow.push(db, ctx, unlock, on, by=by, why=why)


def manual_options(unlock: FigureUnlock) -> list[dict[str, str]]:
    return flow.manual_options(unlock)


def stage_label(unlock: FigureUnlock) -> str:
    return flow.stage_label(unlock)


def waiting_for_pack(db: Session, tier: str) -> list[FigureUnlock]:
    return list(db.scalars(select(FigureUnlock).where(FigureUnlock.flow_step == "wait_pack", FigureUnlock.tier == tier)))


def now() -> datetime:
    return utcnow()
