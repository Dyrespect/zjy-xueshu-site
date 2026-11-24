"""figure.contribute 别人参与的口子：标签不对我来改（带「改成什么」和署名）、版权方要求删除。

投图（/submissions）、提需求（/requests）要传图片，接口照旧在 figures/router.py，署名已有；这里收两种 JSON 的。
限流、蜜罐是接口那层的事（router 先过了才调这里）。
"""

from __future__ import annotations

import re
from datetime import timedelta

from app.core.db import utcnow
from app.core.events import record_event
from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.figures.inbox import FEEDBACK_REASONS, clean, clean_text
from app.figures.models import FigureFeedback, FigureTakedown
from app.figures.node_models import ContributeIn, ContributeOut

_ID = re.compile(r"/figure/(\d{1,6})|(?<![\d/.])(\d{1,6})(?![\d.])")


def figure_ids_in(text: str) -> list[int]:
    """从「图的网址或号」里认出号：…/figure/2972、2972、「图 2972」都行。"""
    out: list[int] = []
    for m in _ID.finditer(text or ""):
        n = int(m.group(1) or m.group(2))
        if n not in out:
            out.append(n)
    return out[:50]


def handler(call: NodeCall, data: ContributeIn) -> NodeResult:
    db = call.db
    if data.kind == "tag_fix":
        if data.figure_id is None or data.reason not in FEEDBACK_REASONS:
            return NodeResult(exit="bad", detail="缺图号或「哪里不对」")
        proposed = {k: clean(str(v), 120) for k, v in (data.proposed or {}).items() if k in ("what", "code") and str(v).strip()}
        row = FigureFeedback(figure_id=data.figure_id, reason=data.reason, note=clean_text(data.note, 500),
                             query=clean(data.query, 300), search_id=data.search_id, ip=data.ip,
                             proposed=proposed, credit=clean(data.credit, 40))
        db.add(row)
        db.flush()
        record_event(db, "figures.feedback", f"figure:{data.figure_id}",
                     {"reason": data.reason, "note": row.note[:200], "proposed": proposed, "credit": row.credit})
        msg = (f"收到了。审过以后这张图下面会写「标签由 {row.credit} 改过」。" if row.credit and proposed
               else "收到了，我们会核对这张图的标签。")
        return NodeResult(exit="received", output=ContributeOut(id=row.id, kind="tag_fix", message=msg))

    # takedown：版权方要求删除，48 小时内从网站和下一版图库包里撤
    text = clean_text(data.figures_text, 2000)
    contact = clean(data.contact, 200)
    if not text or not contact:
        return NodeResult(exit="bad", detail="写上是哪几张图、怎么联系你")
    hours = int(getattr(call.ctx, "takedown_hours", 48) or 48)
    deadline = utcnow() + timedelta(hours=hours)
    ids = figure_ids_in(text)
    row = FigureTakedown(figure_ids=ids, figures_text=text, holder=clean(data.holder, 200), contact=contact,
                         reason=clean_text(data.note, 2000), deadline_at=deadline, ip=data.ip)
    db.add(row)
    db.flush()
    record_event(db, "figures.takedown", f"figure_takedown:{row.id}", {"figure_ids": ids, "holder": row.holder})
    notifier = getattr(call.ctx, "notifier", None)
    if notifier is not None:
        notifier.send(f"【图库·版权问题】{row.holder or '有人'}要求删除图 {ids or text[:60]}，{hours} 小时内处理："
                      f"后台「聚人」→「版权下架」点下架（截止 {deadline.strftime('%m-%d %H:%M')} UTC）。", link="/admin/gather", level="urgent", kind="图库版权删除")
    msg = f"收到了。我们会在 {hours} 小时内核实并从网站和下一版图库包里撤下，处理结果发到你留的联系方式。"
    return NodeResult(exit="received", output=ContributeOut(id=row.id, kind="takedown", message=msg,
                                                            deadline_at=deadline.isoformat()))


CARD = NodeCard(
    id="figure.contribute",
    name="别人参与的口子",
    description="每张图旁「标签不对，我来改」（可以直接写改成什么、留署名）、页脚「版权问题」（版权方要求删除，48 小时内撤）；"
                "投图、提需求两张表单要传图，接口照旧（署名已有）。收进去以后署名显示在网站上。",
    category="获客",
    tech=["FastAPI POST /api/figures/{id}/feedback（加 proposed、credit）、POST /api/figures/takedown（新）",
          "表 figure_feedback（加 proposed、credit、decision）、figure_takedowns（新）", "限流、蜜罐在接口那层（已有）",
          "飞书通知（版权问题马上通知负责人）"],
    input_model=ContributeIn,
    output_model=ContributeOut,
    exits=[
        NodeExit(key="received", label="收到", kind="ok"),
        NodeExit(key="bad", label="缺必填", kind="fail"),
    ],
    config=["FIGURE_RATE_LIMIT_PER_HOUR：同 IP 每小时每类条数", "takedown_hours：版权下架时限（后台聚人设置，默认 48）"],
    emits=["figures.feedback（content 加 proposed、credit）", "figures.takedown"],
    listens=["无"],
    replaceable=["暂无"],
    failure="蜜罐填了照常回「收到了」但不入库（接口层）；同 IP 每小时每类 10 条；每条只记一次，不重试。",
    owner="L",
    status="要改",
)
register(CARD, handler)
