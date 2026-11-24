"""revision.collect 收修改。"""

from __future__ import annotations

import hashlib
import json

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.delivery import versions
from app.delivery.checks import DOC
from app.intake import service
from app.intake.config_store import load_config
from app.intake.models import Order, Revision


class RevisionItem(BaseModel):
    page: int | None = Field(default=None, ge=1, le=500, description="第几页（水印版底栏的第 N 页）；空 = 整体意见")
    text: str = Field(min_length=1, max_length=2000, description="改成什么，客人原话照抄")
    files: list[int] = Field(default_factory=list, description="这一条附的文件（下面 files 里的下标）")


class RevisionFile(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    data: bytes
    content_type: str = ""


class RevisionIn(BaseModel):
    order_id: int
    items: list[RevisionItem] = Field(default_factory=list, max_length=60, description="逐页的修改")
    text: str = Field(default="", max_length=8000, description="只给了一段话时放这里（按「第 N 页」拆，拆不出来算整体意见）")
    files: list[RevisionFile] = Field(default_factory=list, max_length=10, description="截图、圈改图")
    based_on_round: int | None = Field(default=None, description="在第几版上提的（交付页带上；不是最新一版就不收）")
    source: str = Field(default="bot", description="bot 助手在聊天里问清的 | delivery 交付页提的 | admin 后台代填")


class RevisionOut(BaseModel):
    free: bool
    revisions_left: int
    revision_id: int | None = None
    brief: str = ""
    duplicate: bool = False


def _fail(what: str, fix: str) -> NodeResult:
    return NodeResult(exit="fail", detail=f"{what}。怎么改：{fix}。说明：{DOC} 第 4.4 节")


def handler(call: NodeCall, data: RevisionIn) -> NodeResult:
    db = call.db
    o = db.get(Order, data.order_id)
    if o is None:
        return NodeResult(exit="fail", detail="没有这单")
    s = versions.settings()
    items = [i for i in data.items if i.text.strip()]
    if not items and data.text.strip():
        items = [RevisionItem(page=x.get("page"), text=x["text"][:2000]) for x in service.split_revision_text(data.text)]
    if not items:
        return _fail("没写要改什么", "说一下改哪一页、改成什么")
    if data.based_on_round is not None and data.based_on_round != o.delivery_round:
        return _fail(f"你看的是第 {data.based_on_round} 版，现在已经是第 {o.delivery_round} 版", "刷新页面，在最新一版上提")
    n = versions.page_count_of(db, o)
    bad = sorted({i.page for i in items if i.page is not None and n and i.page > n})
    if bad:
        return _fail(f"第 {'、'.join(map(str, bad))} 页不存在（共 {n} 页）", "页码看水印版底栏的「第 N 页」")
    whole = [i for i in items if i.page is None]
    if data.source == "delivery" and len(whole) > s.DELIVERY_WHOLE_ITEMS_MAX:
        return _fail(f"整体意见写了 {len(whole)} 条（最多 {s.DELIVERY_WHOLE_ITEMS_MAX} 条）", "能落到某一页的，写到那一页下面")
    if any(len(i.text.strip()) < 2 for i in items):
        return _fail("有一条只写了一个字", "写清楚改成什么")

    rows = []
    for i in sorted(items, key=lambda x: (x.page is None, x.page or 0)):
        names = [data.files[k].name for k in i.files if 0 <= k < len(data.files)]
        text = i.text.strip() + (f"（附件：{'、'.join(names)}）" if names else "")
        rows.append({"page": i.page, "text": text})
    digest = hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    for rev in db.scalars(select(Revision).where(Revision.order_id == o.id, Revision.based_on_round == o.delivery_round)):
        old = hashlib.sha256(json.dumps(rev.items or [], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        if old == digest:  # 同一页面重复点了提交
            left = service.revisions_left(o, load_config(db))
            return NodeResult(exit="ok" if rev.free else "need_code",
                              output=RevisionOut(free=rev.free, revisions_left=left, revision_id=rev.id, brief=rev.text, duplicate=True))
    if data.source == "delivery" and service.open_revision(db, o) is not None:
        return _fail("上一轮修改还没改完", "等改好的这一版交上来再提；急的话在聊天里跟助手说")
    try:
        rev = service.submit_revision(db, call.ctx, o, items=rows, files=[(f.name, f.data, f.content_type) for f in data.files],
                                      source=data.source)
    except ValueError as e:
        return NodeResult(exit="fail", detail=str(e))
    left = service.revisions_left(o, load_config(db))
    return NodeResult(exit="ok" if rev.free else "need_code",
                      output=RevisionOut(free=rev.free, revisions_left=left, revision_id=rev.id, brief=rev.text))


CARD = NodeCard(
    id="revision.collect",
    name="收修改",
    description="客人要改：逐页问清楚改哪页、改成什么（附截图），一次收齐，整理成改稿单交给制作方，订单进「修改中」；"
                "改好的那版再交，回到「已交水印版」等确认。含一轮，用完了记下来、告诉客人买「再改一轮」。",
    category="制作",
    tech=["交付页逐页「这页要改」表单（POST /api/delivery/{token}/revision）", "接单助手的提修改工具",
          "订单中枢 service.submit_revision（intake_revisions、制作方会话的改稿单）"],
    input_model=RevisionIn,
    output_model=RevisionOut,
    exits=[NodeExit(key="ok", label="改稿单交给制作方了", kind="ok"),
           NodeExit(key="need_code", label="修改轮数用完了，记下来，要再改一轮的码", kind="fail"),
           NodeExit(key="fail", label="页码不存在、没写内容、不是最新一版、上一轮还没改完", kind="fail")],
    config=["revisions_included：含几轮（订单中枢设置）", "config.delivery.revision_hours：改稿多久交下一版（写进改稿单）",
            "DELIVERY_WHOLE_ITEMS_MAX：整体意见最多几条（默认 3，逼客人落到页）"],
    emits=["delivery.revision", "intake.production_message", "intake.stage"],
    listens=["无"],
    replaceable=["来源可换：交付页（默认）、聊天（助手工具）、后台代填", "改稿单格式可换（现在是一条一行的文字，以后可以给制作方结构化 JSON）"],
    failure="同一版同样的内容重复提交按内容摘要去重（返回上一次的结果，不重复扣轮数）；轮数用完不交制作方、记给负责人。",
    owner="E",
    status="已有",
)
register(CARD, handler)
