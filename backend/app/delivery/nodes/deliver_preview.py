"""deliver.preview 交付页：发布水印版、到期前提醒。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.core.events import record_event
from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, has_handler, register, run_node
from app.delivery import outbound, release, versions
from app.intake import flow, service
from app.intake.config_store import load_config
from app.intake.flow import StageError
from app.intake.models import Order

REMIND_DEFAULT = "第 {round} 版还没确认，{when}会自动确认收货并发可编辑 PPT 和讲稿；要改在那之前提：{url}"


class PreviewIn(BaseModel):
    order_id: int
    via: Literal["flow", "call"] = Field(default="call", description="flow：引擎进「发布」这一步时调；call：后台「重新发布」或模块 B 的计时器")
    action: Literal["publish", "remind"] = Field(default="publish", description="publish 发布这一版；remind 自动确认前提醒一次（模块 B 的计时器调）")


class PreviewOut(BaseModel):
    order_id: int = 0
    round: int
    delivery_url: str = ""
    outbox_id: int | None = None
    sent: str = ""


def _remind(call: NodeCall, o: Order) -> NodeResult:
    if o.flow_step != "watermarked" or o.delivered_at is None:
        return NodeResult(exit="fail", detail=f"这单现在是「{flow.stage_label(o)}」，不在等客人看水印版")
    cfg = load_config(call.db)
    when = versions.fmt_when(versions.auto_confirm_at(call.db, o))
    tpl = cfg.delivery.texts.get("remind") or REMIND_DEFAULT
    try:
        text = tpl.format(round=o.delivery_round, when=when, url=call.ctx.delivery_url(o))
    except (KeyError, IndexError):
        text = tpl
    res = outbound.send_text(call.db, call.ctx, o, text, dedupe_key=f"remind:{o.id}:{o.delivery_round}", by=call.by)
    return NodeResult(exit="reminded", output=PreviewOut(order_id=o.id, round=o.delivery_round, delivery_url=call.ctx.delivery_url(o),
                                                         outbox_id=res.get("outbox_id"), sent=str(res.get("status", ""))))


def handler(call: NodeCall, data: PreviewIn) -> NodeResult:
    o = call.db.get(Order, data.order_id)
    if o is None:
        return NodeResult(exit="fail", detail="没有这单")
    if data.action == "remind":
        return _remind(call, o)
    if data.via == "call":
        try:
            flow.push(call.db, call.ctx, o, "proof_ready", by=call.by, why="重新发布水印版")
        except StageError as e:
            return NodeResult(exit="fail", detail=str(e))
        return NodeResult(exit="published", output=PreviewOut(order_id=o.id, round=o.delivery_round, delivery_url=call.ctx.delivery_url(o)))
    # 不加急的单，第一版最早在加急承诺时长之后才发（Edison 11-19，release.py）：没到点就停在这一步，后台圈到点再推
    v_next = versions.version_of(call.db, o.id, o.delivery_round + 1)
    until = release.hold_until(call.db, o, v_next)
    if until is not None:
        if v_next is not None and v_next.release_at is None:
            v_next.release_at = until
            record_event(call.db, "delivery.release_held", f"order:{o.id}", {
                "round": v_next.round, "until": until.isoformat(), "by": call.by})
        return NodeResult(exit="held", output=PreviewOut(order_id=o.id, round=o.delivery_round + 1, delivery_url=call.ctx.delivery_url(o)),
                          detail=f"不加急的单，水印版压到 {versions.fmt_when(until)} 自动发给客人（后台能点「现在就发」）")
    try:
        ob = service.publish_preview(call.db, call.ctx, o, by=call.by)  # 交过的版数 + 1，只发交付页链接
    except ValueError as e:
        return NodeResult(exit="fail", detail=str(e))
    v = versions.mark_published(call.db, o)
    record_event(call.db, "delivery.version_published", f"order:{o.id}", {
        "round": o.delivery_round, "version": v.id if v else None, "pages": v.page_count if v else None,
        "page_sha256": (v.page_sha256 if v else [])[:120], "by": call.by})
    if o.delivery_round == 1 and has_handler("deliver.sla"):
        run_node("deliver.sla", NodeCall(call.db, call.ctx, call.by, o.id), {"order_id": o.id, "at_publish": True})
    return NodeResult(exit="published", output=PreviewOut(order_id=o.id, round=o.delivery_round, delivery_url=call.ctx.delivery_url(o),
                                                          outbox_id=ob.id if ob else None, sent="queued" if ob else ""))


CARD = NodeCard(
    id="deliver.preview",
    name="交付页（发布水印版）",
    description="把这一版水印版发布给客人：聊天里只发交付页链接（不发 pptx），客人在页面上逐页看、逐页提修改、确认收货，"
                "确认后在同一页下载最终版。平台早就确认收货的单，发布后流程直接走到已完成、放最终版。"
                "自动确认前 24 小时提醒一次（模块 B 的计时器调 action=remind）。",
    category="交付",
    tech=["交付页 /d/<令牌>（app/delivery/router.py，随机长令牌、noindex）", "前端区块 proof-viewer、revision-sheet、receipt-panel、final-files",
          "订单中枢 service.publish_preview（待发 → 网页聊天 / 微信客服）",
          "提醒：customer.memory(pick_session) → entry.wecom / entry.webchat（模块 D 没登记时退回待发）"],
    input_model=PreviewIn,
    output_model=PreviewOut,
    exits=[NodeExit(key="published", label="发布了", kind="ok"),
           NodeExit(key="reminded", label="提醒发了（或进了待发）", kind="ok"),
           NodeExit(key="held", label="不加急的单还没到加急承诺时长：压着，到点自动发", kind="wait"),
           NodeExit(key="fail", label="这一版没有水印图、暂停中、还没人认领", kind="fail")],
    config=["config.delivery.texts：publish_self / publish_platform / remind 几句话", "config.delivery.confirm_sources_by_platform：说「点确认收货」还是「去平台确认」",
            "config.auto_confirm_days：页面写几点自动确认（和模块 B 的计时器读同一个）"],
    emits=["delivery.proof_published", "delivery.version_published", "delivery.sent", "intake.stage"],
    listens=["无"],
    replaceable=["发布方式可换：交付页链接（默认）、微信里直接发前 3 页水印图 + 链接、只发 PDF 链接（配 pdf_image）"],
    failure="不加急的单第一版压到加急承诺时长之后（release.py，后台圈到点再推，后台能「现在就发」）；一版只发布一次（版数在订单中枢 + 1）；暂停中不发布，申请关闭后订单中枢再推一下；提醒按 remind:单:版 只发一次；"
            "微信 48 小时窗口关着由渠道层等客人再开口补发，交付页照常能看。",
    owner="E",
    status="已有",
)
register(CARD, handler)
