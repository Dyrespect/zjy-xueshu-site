"""figure.unlock_verify 转发核验（可换）：流程一进「核验」就跑，按这次领取记下的方式判。"""

from __future__ import annotations

from app.core.events import record_event
from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.gather import verifiers
from app.gather.config import load_config
from app.gather.models import FigureUnlock, UnlockEvidence
from app.gather.models_io import VerifyIn, VerifyOut
from app.gather.service import now


def handler(call: NodeCall, data: VerifyIn) -> NodeResult:
    db = call.db
    unlock = db.get(FigureUnlock, data.subject_id)
    if unlock is None:
        return NodeResult(exit="fail", output=VerifyOut(verdict="fail", verifier="", reason="没有这次领取"))
    cfg = call.ctx.cfg or load_config(db)
    evidence = db.get(UnlockEvidence, data.evidence_id) if data.evidence_id else None
    name, v = verifiers.run(db, unlock, evidence, cfg)
    unlock.verifier = name
    unlock.verdict_reason = v.reason[:300]
    if v.verdict == "pass":
        unlock.passed_at = now()
    record_event(db, "figure.unlock_verified", f"figure_unlock:{unlock.id}",
                 {"verdict": v.verdict, "verifier": name, "reason": v.reason[:200], "evidence_id": data.evidence_id})
    return NodeResult(exit=v.verdict, output=VerifyOut(verdict=v.verdict, verifier=name, reason=v.reason), detail=v.reason)


CARD = NodeCard(
    id="figure.unlock_verify",
    name="转发核验（可换）",
    description="判断这个人有没有完成「转发」。默认收到截图就算（截图存着，负责人抽查）；可以换成「关注公众号」「他的链接带来 N 个新访客」"
                "「负责人在后台看过再发」，换的时候只改后台聚人设置里的「核验方式」一项，流程文件不动。",
    category="关口",
    tech=["实现接口 UnlockVerifier（app/gather/verifiers.py）：screenshot_trust、follow_gzh、share_visits、manual",
          "截图走 core/storage（不出对外接口）", "sha256 认重复截图", "看图核验（screenshot_model）要付费入口，Edison 点头前不做"],
    input_model=VerifyIn,
    output_model=VerifyOut,
    exits=[
        NodeExit(key="pass", label="过了", kind="ok"),
        NodeExit(key="need_more", label="再交一张 / 再来几个人 / 去公众号", kind="wait"),
        NodeExit(key="wait_admin", label="等负责人看", kind="wait"),
        NodeExit(key="fail", label="不给", kind="fail"),
    ],
    config=["verifier：用哪种（后台聚人设置；默认 screenshot_trust）", "share_visits_n：share_visits 要几个新访客（3，拍的）"],
    emits=["figure.unlock_verified（verdict、用的哪种、理由）"],
    listens=["无（funnel.share_visit 由接口转成流程事件 share_visit，只有用 share_visits 时连线才通）"],
    replaceable=["screenshot_trust 转发核验（默认）", "follow_gzh 关注公众号", "share_visits 带来 N 个新访客",
                 "manual 负责人在后台点", "screenshot_model 看图核验（以后，要付费入口）"],
    failure="同一张图（sha256 相同）再交 → need_more；被标过假截图的访客之后都 fail；一次领取只会走到一次「发链接」（流程只往下走）。",
    owner="L",
    status="要新做",
)
register(CARD, handler)
