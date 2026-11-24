"""entry.notice 固定话术。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.channels import entries, texts
from app.channels.entry_config import load_entry_config
from app.channels.entry_types import OutboundMessage, Purpose
from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register, run_node
from app.intake import brief
from app.intake.config_store import load_config
from app.intake.models import Customer, Order

COLLECT_STAGES = ("paid", "claimed", "collecting")


class NoticeIn(BaseModel):
    session_id: int
    template: str = Field(min_length=1, max_length=40, description="entry_texts 里的键：claim_ok、claim_taken、file_refused……")
    order_id: int | None = None
    code: str = ""
    extra: dict[str, Any] = Field(default_factory=dict, description="模板里别的占位符")
    purpose: Purpose = "claim"
    dedupe_key: str = ""


class NoticeOut(BaseModel):
    message: OutboundMessage
    shortened: bool = False


def handler(call: NodeCall, data: NoticeIn) -> NodeResult:
    db = call.db
    cfg, ecfg = load_config(db), load_entry_config(db)
    c = db.get(Customer, data.session_id)
    order = db.get(Order, data.order_id) if data.order_id else None
    kw: dict[str, Any] = {k: v for k, v in data.extra.items() if v is not None}
    kw.setdefault("last4", texts.last4(data.code))
    kw.setdefault("intro_url", ecfg.site_url)
    url = ""
    if order is not None:
        collect = run_node("intake.collect", call, {"order_id": order.id}).output if order.stage in COLLECT_STAGES else None
        url = call.ctx.delivery_url(order) if hasattr(call.ctx, "delivery_url") else ""
        hours = texts.hours_for(cfg, order)
        kw.setdefault("sku_name", texts.sku_name_of(cfg, order))
        if data.template == "claim_ok":  # 资料清单（materials / required_list / optional_list）
            for k, v in texts.checklist_lists(db, order, collect).items():
                kw.setdefault(k, v)
        kw.setdefault("hours", hours if hours is not None else "约定的")
        kw.setdefault("progress", texts.customer_progress(order, collect))
        kw.setdefault("next_step", texts.next_step(order, collect, url))
        kw.setdefault("url", url)
        kw.setdefault("delivery_url", url)
    full = texts.text(cfg, data.template, **kw)
    if data.template == "welcome_plain" and cfg.welcome_text.strip():
        full = cfg.welcome_text.strip()  # 后台「设置」页的欢迎语（网页聊天顶上那句也是它）
    if data.template in ("welcome_plain", "visitor_limited") and ecfg.site_url and ecfg.site_url not in full:
        full = f"{full}\n{texts.text(cfg, 'welcome_with_intro', intro_url=ecfg.site_url)}"
    spec = entries.spec_for(c.channel) if c is not None else None
    limit = spec.caps.text_max_bytes if spec is not None else None
    short = texts.text(cfg, "claim_short", **kw) if data.template == "claim_ok" and url else full
    if data.template == "claim_ok" and order is not None and brief.editable(order) and not brief.confirmed(db, order):
        invite = texts.text(cfg, "brief_invite", brief_url=brief.brief_url(call.ctx, order))  # 需求卡入口（09 需求引导）
        full, short = f"{full}\n{invite}", f"{short}\n{invite}"
    out_text, shortened = texts.fit_bytes(full, short, limit)
    if limit is not None and len(out_text.encode("utf-8")) > limit:
        out_text = out_text.encode("utf-8")[: limit - 3].decode("utf-8", "ignore") + "…"
        shortened = True
    msg = OutboundMessage(session_id=data.session_id, purpose=data.purpose, text=out_text, dedupe_key=data.dedupe_key,
                          order_id=order.id if order is not None else None, fallback_url=url or None)
    return NodeResult(exit="too_long" if shortened else "ok", output=NoticeOut(message=msg, shortened=shortened))


CARD = NodeCard(
    id="entry.notice",
    name="固定话术",
    description="把认领结果、资料清单、上限提醒、「去平台点确认收货」这类固定的话拼好交给入口发。不调模型，不写价格；"
                "按入口一条的字数上限合成一条，装不下改发短版 + 交付页链接。",
    category="对话",
    tech=["Python 模板（app/channels/texts.py）", "设置 entry_texts（订单中枢，后台能改）覆盖默认", "run_node 调 intake.collect 拿清单"],
    input_model=NoticeIn,
    output_model=NoticeOut,
    exits=[NodeExit(key="ok", label="拼好了", kind="ok"),
           NodeExit(key="too_long", label="超过入口字数上限，改成短版 + 交付页链接", kind="ok")],
    config=["entry_texts：模板（入口设计附录 A）", "occasions 的 must / nice、materials：资料清单的字（app/intake/materials.py 拼）",
            "checklists：哪几样必需（经 intake.collect）", "entry_config.site_url：官网链接"],
    emits=["无"],
    listens=["无"],
    replaceable=["换模板；以后可加「模型润色」节点，但认领、清单类必须原样"],
    failure="纯函数（只读），随便重试。",
    owner="D",
    status="要新做",
)
register(CARD, handler)
