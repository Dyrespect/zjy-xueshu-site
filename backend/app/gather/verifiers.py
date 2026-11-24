"""figure.unlock_verify 的几种实现（07 第十五节卡 5「可换」）：后台「聚人设置」改 verifier 一项就换，流程文件不动。

每种实现吃同一份事实（这次领取、刚交的截图、设置），吐一个结论：pass 过了 / need_more 再来 / wait_admin 等负责人 / fail 不给。
不让模型直接判过不过；以后接看图核验（screenshot_model）也是先读出群名、人数、时间、可见范围再按规则判，要付费入口，Edison 点头才接。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.gather.models import FigureUnlock, UnlockEvidence


@dataclass
class Verdict:
    verdict: str
    reason: str


class UnlockVerifier(Protocol):
    def __call__(self, db: Session, unlock: FigureUnlock, evidence: UnlockEvidence | None, cfg: dict[str, Any]) -> Verdict: ...


def _marked_fake(db: Session, unlock: FigureUnlock) -> bool:
    """这个访客以前交的截图被负责人标过假的：之后都不给。"""
    n = db.scalar(select(func.count()).select_from(UnlockEvidence).where(
        UnlockEvidence.visitor == unlock.visitor, UnlockEvidence.admin_mark == "fake")) or 0
    return n > 0


def _reused(db: Session, evidence: UnlockEvidence) -> bool:
    """同一张图（内容一样）以前交过：别人的截图、自己交第二遍都算。"""
    n = db.scalar(select(func.count()).select_from(UnlockEvidence).where(
        UnlockEvidence.sha256 == evidence.sha256, UnlockEvidence.id != evidence.id)) or 0
    return n > 0


def screenshot_trust(db: Session, unlock: FigureUnlock, evidence: UnlockEvidence | None, cfg: dict[str, Any]) -> Verdict:
    if evidence is None:
        return Verdict("need_more", "交一张转发后的截图")
    if _marked_fake(db, unlock):
        return Verdict("fail", "之前交的截图核对下来不是转发截图，这次不能发；有疑问在页脚「网站意见」里说")
    if _reused(db, evidence):
        return Verdict("need_more", "这张截图之前交过了，换一张你自己转发后的截图")
    return Verdict("pass", "收到截图，链接发你了；截图我们留着抽查")


def share_visits(db: Session, unlock: FigureUnlock, evidence: UnlockEvidence | None, cfg: dict[str, Any]) -> Verdict:
    n = int(cfg.get("share_visits_n") or 3)
    if _marked_fake(db, unlock):
        return Verdict("fail", "之前交的截图核对下来不是转发截图，这次不能发")
    if unlock.share_visits >= n:
        return Verdict("pass", f"你的链接已经带来 {unlock.share_visits} 个新朋友，链接发你了")
    return Verdict("need_more", f"你的链接已经带来 {unlock.share_visits} 个新朋友，再来 {n - unlock.share_visits} 个就自动发链接")


def manual(db: Session, unlock: FigureUnlock, evidence: UnlockEvidence | None, cfg: dict[str, Any]) -> Verdict:
    if evidence is None:
        return Verdict("need_more", "交一张转发后的截图")
    if _marked_fake(db, unlock):
        return Verdict("fail", "之前交的截图核对下来不是转发截图，这次不能发")
    if _reused(db, evidence):
        return Verdict("need_more", "这张截图之前交过了，换一张你自己转发后的截图")
    return Verdict("wait_admin", "收到截图，我们看过就把链接放在这里，一般当天；关掉页面也不要紧，下次打开还在")


def follow_gzh(db: Session, unlock: FigureUnlock, evidence: UnlockEvidence | None, cfg: dict[str, Any]) -> Verdict:
    """关注公众号那条路：网页查不到谁关注了（个人未认证订阅号没有接口），链接由公众号关键词回复发，这里只引导。"""
    return Verdict("need_more", f"在公众号 {cfg.get('gzh_name')} 回复「{cfg.get('gzh_keyword')}」拿链接")


IMPLS: dict[str, UnlockVerifier] = {
    "screenshot_trust": screenshot_trust,
    "share_visits": share_visits,
    "manual": manual,
    "follow_gzh": follow_gzh,
}

_RANK = {"pass": 0, "wait_admin": 1, "need_more": 2, "fail": 3}


def run(db: Session, unlock: FigureUnlock, evidence: UnlockEvidence | None, cfg: dict[str, Any]) -> tuple[str, Verdict]:
    """按这次领取发起时记下的方式逐个判，任一过就算；都不过取最接近的那个结论。"""
    names = [v for v in (unlock.verifiers or []) if v in IMPLS] or [cfg.get("verifier") or "screenshot_trust"]
    best: tuple[str, Verdict] | None = None
    for name in names:
        v = IMPLS[name](db, unlock, evidence, cfg)
        if best is None or _RANK[v.verdict] < _RANK[best[1].verdict]:
            best = (name, v)
        if v.verdict == "pass":
            break
    assert best is not None
    return best
