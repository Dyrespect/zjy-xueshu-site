"""funnel.track 来访与来源：每个来图库的人记一次从哪来；转发链接带来的新访客记到转发人头上。"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select

from app.core.db import utcnow
from app.core.events import record_event
from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.gather.models import FigureUnlock, FunnelVisit
from app.gather.models_io import VisitIn, VisitOut


def handler(call: NodeCall, data: VisitIn) -> NodeResult:
    db, gs = call.db, call.ctx.settings
    now = utcnow()
    hour = db.scalar(select(func.count()).select_from(FunnelVisit).where(
        FunnelVisit.ip == data.ip, FunnelVisit.created_at >= now - timedelta(hours=1))) or 0
    if data.ip and hour >= gs.VISIT_RATE_PER_HOUR:
        return NodeResult(exit="limited", detail="同一 IP 来得太频繁")
    src = (data.src or "").strip().lower()[:32]
    if src and src not in gs.FUNNEL_SOURCES and not src.startswith("tuku_"):
        src = "other"  # 白名单外的来源记成 other（07 第十一节检查 5）
    share = (data.share or "").strip().upper()[:12]
    if share and not src:
        src = "share"
    unlock = db.scalar(select(FigureUnlock).where(FigureUnlock.share_code == share)) if share else None
    share_new = False
    if unlock is not None and unlock.visitor != data.visitor:  # 转发人自己点自己的链接不算
        seen = db.scalar(select(func.count()).select_from(FunnelVisit).where(
            FunnelVisit.visitor == data.visitor, FunnelVisit.share_code == share)) or 0
        share_new = seen == 0
    recent = db.scalar(select(FunnelVisit.id).where(
        FunnelVisit.visitor == data.visitor,
        FunnelVisit.created_at >= now - timedelta(minutes=gs.FUNNEL_DEDUPE_MINUTES)).limit(1))
    if recent is not None and not share_new:
        return NodeResult(exit="dup", output=VisitOut(visitor=data.visitor, src=src, counted=False))
    db.add(FunnelVisit(visitor=data.visitor, src=src, share_code=share or None, share_counted=share_new,
                       landing=data.landing[:300], referrer_host=data.referrer_host[:100], ip=data.ip))
    if share_new and unlock is not None:
        unlock.share_visits = (unlock.share_visits or 0) + 1
        record_event(db, "funnel.share_visit", f"figure_unlock:{unlock.id}", {"visitor": data.visitor[:12],
                                                                              "visits": unlock.share_visits})
    db.flush()
    return NodeResult(exit="counted", output=VisitOut(visitor=data.visitor, src=src, counted=True, share_new=share_new,
                                                      share_unlock_id=unlock.id if share_new and unlock else None))


CARD = NodeCard(
    id="funnel.track",
    name="来访与来源记录",
    description="每个来图库网站的人记一次「从哪来」（公众号、小红书、别人转发、GitHub、插件、网盘包）；转发链接带来的新访客记到转发人头上。"
                "后面领图库、点下单都挂同一个来源，周报按它算。",
    category="运营",
    tech=["FastAPI POST /api/gather/visit（前端首屏发一次，不等）", "浏览器 localStorage 匿名访客号（读写包 try/catch）",
          "表 funnel_visits；figure_unlocks.share_visits 计数"],
    input_model=VisitIn,
    output_model=VisitOut,
    exits=[
        NodeExit(key="counted", label="记上了", kind="ok"),
        NodeExit(key="dup", label="30 分钟内记过", kind="ok"),
        NodeExit(key="limited", label="同 IP 太频繁", kind="fail"),
    ],
    config=["FUNNEL_SOURCES：来源白名单，不在里面的记 other", "FUNNEL_DEDUPE_MINUTES：同一访客多久只记一次（30）",
            "VISIT_RATE_PER_HOUR：同 IP 每小时上限"],
    emits=["funnel.share_visit（带分享码、而且是这个分享码第一次见到的访客；接口再在那次领取上发流程事件 share_visit）"],
    listens=["无"],
    replaceable=["暂无（不接第三方统计脚本：数据要和订单在一个库里算）"],
    failure="前端发完不等，记不上不挡页面；同一访客 30 分钟内只记一次（幂等）；转发人自己点自己的链接不算。",
    owner="L",
    status="要新做",
)
register(CARD, handler)
