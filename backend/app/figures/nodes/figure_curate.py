"""figure.curate 审核与收录：改标签点通过就叠到索引上、网站马上用；版权方要求删除点下架，网站马上不显示、下一版包里去掉。"""

from __future__ import annotations

from app.core.db import utcnow
from app.core.events import record_event
from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.figures import overlay
from app.figures.models import (
    DECISION_APPROVED,
    DECISION_HIDDEN,
    DECISION_NEW,
    DECISION_REJECTED,
    STATUS_DONE,
    FigureFeedback,
    FigureOverride,
    FigureSubmission,
    FigureTakedown,
)
from app.figures.node_models import CurateIn, CurateOut

MODELS = {"tag_fix": FigureFeedback, "submit": FigureSubmission, "takedown": FigureTakedown}


def handler(call: NodeCall, data: CurateIn) -> NodeResult:
    db = call.db
    row = db.get(MODELS[data.kind], data.item_id)
    if row is None:
        return NodeResult(exit="bad", detail="没有这一条")
    if row.decision != DECISION_NEW:
        return NodeResult(exit="already", detail=f"这一条已经审过了（{row.decision}）")
    now = utcnow()
    ids: list[int] = []
    out_ids: list[int] = []
    credit = getattr(row, "credit", "") or ""
    if data.decision == "reject":
        row.decision = DECISION_REJECTED
        status = "rejected"
    elif data.kind == "takedown":
        if data.decision != "hide":
            return NodeResult(exit="bad", detail="版权问题只能「下架」或「不通过」")
        ids = [int(x) for x in (data.edited.get("figure_ids") or row.figure_ids or [])]
        if not ids:
            return NodeResult(exit="bad", detail="没认出是哪几张图：在「改成」里填上图号再下架")
        for fid in ids:
            o = FigureOverride(figure_id=fid, field="hidden", value=True, source_kind="takedown", source_id=row.id)
            db.add(o)
            db.flush()
            out_ids.append(o.id)
        row.figure_ids = ids
        row.decision = DECISION_HIDDEN
        status = "hidden"
    elif data.kind == "tag_fix":
        merged = {**(row.proposed or {}), **{k: v for k, v in (data.edited or {}).items() if k in ("what", "code") and v}}
        if not merged:
            return NodeResult(exit="bad", detail="没写改成什么：在「改成」里填上再通过，或者点「不通过」")
        for field, value in merged.items():
            if field not in ("what", "code"):
                continue
            o = FigureOverride(figure_id=row.figure_id, field=field, value=str(value)[:120], credit=credit,
                               source_kind="feedback", source_id=row.id)
            db.add(o)
            db.flush()
            out_ids.append(o.id)
        ids = [row.figure_id]
        row.proposed = merged
        row.decision = DECISION_APPROVED
        status = "approved"
    else:  # submit：进下一版图库的待收录清单（打标、编向量在 学术汇报/科研绘图2/找图/，不归这里）
        row.decision = DECISION_APPROVED
        status = "approved"
    row.status = STATUS_DONE
    row.handled_at = now
    if data.note:
        row.admin_note = data.note[:300]
    record_event(db, f"figure.contribution_{'rejected' if status == 'rejected' else 'accepted'}",
                 f"figure_{data.kind}:{row.id}", {"kind": data.kind, "status": status, "figure_ids": ids, "credit": credit})
    db.flush()
    if out_ids:
        overlay.refresh(db, getattr(call.ctx, "figure_library", None), getattr(call.ctx, "figure_cache", None))
    exit_key = {"rejected": "rejected", "hidden": "hidden"}.get(status, "approved")
    return NodeResult(exit=exit_key, output=CurateOut(status=status, override_ids=out_ids, credit=credit, figure_ids=ids))


CARD = NodeCard(
    id="figure.curate",
    name="审核与收录",
    description="负责人在后台看改标签、投图、版权问题：改标签点「通过」就叠到索引上、网站马上用新标签并写署名；投图点「收」进下一版图库的待收录清单；"
                "版权方要求删除的点「下架」，网站马上不显示、下一版包里去掉；不通过写一句为什么。",
    category="运营",
    tech=["后台 POST /api/admin/figures/curate/{kind}/{id}", "表 figure_overrides（叠在索引上，figures/overlay.py 读时合并）",
          "Library.set_overlay（搜索、浏览、详情、更多类似、开放接口都过滤下架的）"],
    input_model=CurateIn,
    output_model=CurateOut,
    exits=[
        NodeExit(key="approved", label="通过", kind="ok"),
        NodeExit(key="hidden", label="下架了", kind="ok"),
        NodeExit(key="rejected", label="不通过", kind="ok"),
        NodeExit(key="already", label="审过了", kind="fail"),
        NodeExit(key="bad", label="缺东西（没写改成什么、没认出图号）", kind="fail"),
    ],
    config=["无"],
    emits=["figure.contribution_accepted（kind、figure_ids、credit）", "figure.contribution_rejected"],
    listens=["无"],
    replaceable=["人审（默认）", "以后模型先审、负责人点头"],
    failure="每条只能审一次（new → approved / rejected / hidden）；改标签只改「讲的是什么、图型」两样；版权下架后台列表排最前、标截止时间。",
    owner="L",
    status="要新做",
)
register(CARD, handler)
