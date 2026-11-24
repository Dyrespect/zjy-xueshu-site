"""和制作方（Claude）对话（PRD v2 第六节）。接口在 intake/router.py 的 /api/intake/production，命令行是
scripts/production_cli.py；以后接 API 的话，换成一个调同样接口的小进程。

- 每单一条「制作方会话」（ProductionMessage）：业务员 → 制作方：开单说明、补充要求、问题、回答、改稿单；
  制作方 → 业务员：进度、问题、回答、成品。
- 开单说明：到开工那天跟 inbox 交接一起写（handoff.py 调 `write_brief`），内容就是 要求.md。
- 制作方发消息 → 让机器人跑一趟去转告客户（网页聊天随时发；微信客服 48 小时窗口关着就等客户下次说话）。
- 制作方交一版成品包（最终版 + 每页整页图）→ 流程事件 package_received → 自动出水印图、发布给客户看；
  最终版锁在库里，订单到「已完成」才发（gate.final）。已完成、已交付后再改交的包直接放新的最终版。
- 制作方「开始做」「做好了」只记时间（订单状态由流程引擎按流程定义走）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.events import record_event
from app.core.nodes import NodeCall, run_node
from app.intake import clock, flow, orders, pricing, service
from app.intake.config_store import load_config
from app.intake.models import (
    DELIVERABLE_KINDS,
    PAGE_KIND,
    PRODUCTION_KINDS_TO_SALES,
    Customer,
    FileRecord,
    Order,
    ProductionMessage,
)
from app.intake.service import Ctx
from app.intake.watermark import WatermarkError, check_page

OPEN_STAGES = ("making", "watermarked", "revising", "completed")


def write_brief(db: Session, order: Order, requirements_md: str, where: str) -> ProductionMessage:
    """开单说明 = 要求.md 的内容 + 材料在哪。到开工那天跟 inbox 交接一起写。"""
    text = f"{requirements_md.rstrip()}\n\n材料在：{where}"
    return service.add_production_message(db, order, "to_maker", "开单说明", text, author="system")


def maker_state(o: Order) -> str:
    if o.stage == "void":
        return "作废了，停工"
    if o.stage == "delivered":
        return "最终版发了"
    if o.stage == "completed":
        return "客户确认了，等最终版" if not o.finished_at else "最终版发了"
    if o.stage == "revising":
        return "改稿中"
    if o.stage == "watermarked":
        return "交了水印版，等客户看"
    if o.flow_step in ("proofing", "publish"):
        return "在出水印图"
    if o.maker_done_at:
        return "做好了"
    if o.maker_started_at:
        return "在做"
    return "待开"


def guess_kind(name: str) -> str:
    n = name.lower()
    if n.endswith((".pptx", ".ppt", ".key")):
        return "PPT"
    if n.endswith((".docx", ".doc", ".md", ".txt")):
        return "讲稿"
    if n.endswith(".pdf"):
        return "PDF"
    if n.endswith((".svg", ".ai", ".eps", ".emf", ".png")):
        return "可编辑图"
    return "其他"


def _unread(db: Session, order: Order) -> int:
    return db.scalar(select(func.count()).select_from(ProductionMessage).where(
        ProductionMessage.order_id == order.id, ProductionMessage.direction == "to_maker",
        ProductionMessage.read_at.is_(None))) or 0


def _has_brief(db: Session, order: Order) -> bool:
    return bool(db.scalar(select(func.count()).select_from(ProductionMessage).where(
        ProductionMessage.order_id == order.id, ProductionMessage.kind == "开单说明")))


def order_brief(db: Session, o: Order) -> dict[str, Any]:
    c = db.get(Customer, o.customer_id) if o.customer_id else None
    cfg = load_config(db)
    tier = cfg.tier(o.tier_key)
    return {
        "id": o.id,
        "customer": service.display_name(c) if c else "",
        "stage": o.stage,
        "stage_label": flow.stage_label(o),
        "maker_state": maker_state(o),
        "occasion": o.occasion,
        "title": o.title,
        "duration_min": o.duration_min,
        "present_date": o.present_date,
        "eta_date": o.eta_date,
        "tier": pricing.sku_name(cfg, o.sku, orders.addon_keys(o)) if o.sku else "",
        "max_pages": tier.max_pages if tier else None,
        "due_hours": o.due_hours,
        "rush": o.rush,
        "inbox_folder": o.handoff_folder,
        "delivery_round": o.delivery_round,
        "unread": _unread(db, o),
        "started_at": o.started_at,
    }


def list_orders(db: Session, which: str = "open") -> list[dict[str, Any]]:
    """有开单说明的单（开过工）。open：还没交付完的 + 改稿中的；all：全部（最近 100 单）。"""
    q = select(Order).where(Order.started_at.is_not(None)).order_by(Order.started_at.desc()).limit(100)
    out = []
    for o in db.scalars(q):
        if which == "open" and o.stage not in OPEN_STAGES and not (o.flow_step == "revising_after" or _unread(db, o)):
            continue
        if not _has_brief(db, o):
            continue
        out.append(order_brief(db, o))
    return out


def message_out(m: ProductionMessage, files: dict[int, FileRecord]) -> dict[str, Any]:
    return {
        "id": m.id, "direction": m.direction, "kind": m.kind, "author": m.author, "text": m.text,
        "files": [files[i].filename for i in (m.file_ids or []) if i in files],
        "read_at": m.read_at, "relayed_at": m.relayed_at, "created_at": m.created_at,
    }


def order_detail(db: Session, o: Order) -> dict[str, Any]:
    msgs = service.production_messages(db, o)
    fids = {i for m in msgs for i in (m.file_ids or [])}
    files = {f.id: f for f in db.scalars(select(FileRecord).where(FileRecord.id.in_(fids)))} if fids else {}
    materials = service.order_files(db, o)
    deliverables = service.order_files(db, o, "deliverable")
    return {
        **order_brief(db, o),
        "messages": [message_out(m, files) for m in msgs],
        "materials": [{"name": f.filename, "purpose": f.purpose or "用途没登记", "size": f.size} for f in materials],
        "deliverables": [{"name": f.filename, "kind": f.purpose, "round": f.round, "size": f.size} for f in deliverables],
        "revisions_left": service.revisions_left(o, load_config(db)),
    }


def mark_read(db: Session, o: Order) -> int:
    n = 0
    for m in db.scalars(select(ProductionMessage).where(
            ProductionMessage.order_id == o.id, ProductionMessage.direction == "to_maker", ProductionMessage.read_at.is_(None))):
        m.read_at = utcnow()
        n += 1
    return n


def _ensure_open(o: Order) -> None:
    if o.started_at is None:
        raise ValueError("这单还没开工（没有开单说明）")
    if o.stage == "void":
        raise ValueError("这单已经作废了，停工")


def maker_says(db: Session, ctx: Ctx, o: Order, kind: str, text: str) -> ProductionMessage:
    """制作方发一条（进度 / 问题 / 回答）→ 让机器人跑一趟去转告客户。"""
    _ensure_open(o)
    if kind not in PRODUCTION_KINDS_TO_SALES or kind == "成品":
        raise ValueError("类型只能是：进度、问题、回答")
    if not text.strip():
        raise ValueError("说点什么")
    m = service.add_production_message(db, o, "to_sales", kind, text.strip(), author="maker")
    customer = db.get(Customer, o.customer_id)
    if customer is not None and not customer.human_takeover:
        service.enqueue_job(db, customer, delay=0)
    return m


def maker_package(db: Session, ctx: Ctx, o: Order, files: list[tuple[str, bytes, str]],
                  pages: list[tuple[int, str, bytes, str]], note: str = "") -> dict[str, Any]:
    """制作方交一版成品包（deliver.receive）：最终版存进库（客户这时拿不到）、整页图存成页图，
    发 package_received → 出水印图 → 发布给客户看。已完成、已交付后再改的直接放新的最终版。"""
    _ensure_open(o)
    if not files and not pages:
        raise ValueError("没有文件")
    for no, name, data, _ in pages:
        try:
            check_page(data)
        except WatermarkError as e:
            raise ValueError(f"第 {no} 页（{name}）：{e}") from e
    for name, data, _ in files:
        if not data:
            raise ValueError(f"{name} 是空的")
    # 制作方每次交的是完整的一版：这一版之前存了、还没发布的（上次交的、传了一半的）先作废，不跟新的混
    service.discard_unpublished(db, ctx, o, by="maker", why="制作方重交了这一版")
    names = []
    for name, data, ctype in files:
        kind = guess_kind(name)
        service.add_deliverable(db, ctx, o, filename=Path(name).name, data=data, kind=kind if kind in DELIVERABLE_KINDS else "其他",
                                content_type=ctype)
        names.append(Path(name).name)
    for no, name, data, ctype in pages:
        service.add_deliverable(db, ctx, o, filename=Path(name).name, data=data, kind=PAGE_KIND, content_type=ctype, page_no=no)
    o.maker_done_at = o.maker_done_at or utcnow()
    # 收成品包走节点 deliver.receive（模块 E：齐不齐、页数对不对、缩略图、文件坏，原因三件；收了再发 package_received）
    res = run_node("deliver.receive", NodeCall(db, ctx, "maker", o.id), {"order_id": o.id, "note": note, "source": "maker_cli"})
    if res.exit != "ok":
        raise ValueError(res.detail)
    nxt = res.output.round
    text = f"交了第 {nxt} 版：" + "、".join(names) + (f"，整页图 {len(pages)} 张" if pages else "") + (f"\n{note.strip()}" if note.strip() else "")
    service.add_production_message(db, o, "to_sales", "成品", text, author="maker", relayed=True)
    record_event(db, "intake.maker_delivered", f"order:{o.id}", {"files": names, "pages": len(pages), "round": nxt})
    return {"round": nxt, "files": names, "pages": len(pages), "stage": o.stage, "stage_label": flow.stage_label(o),
            "delivery_url": ctx.delivery_url(o)}


def maker_mark(db: Session, o: Order, what: str) -> Order:
    _ensure_open(o)
    if what == "start":
        o.maker_started_at = o.maker_started_at or utcnow()
    elif what == "done":
        o.maker_started_at = o.maker_started_at or utcnow()
        o.maker_done_at = utcnow()
    else:
        raise ValueError(what)
    o.updated_at = utcnow()
    record_event(db, f"intake.maker_{what}", f"order:{o.id}", {})
    return o


def due_text(o: Order) -> str:
    return f"{clock.fmt_date(o.eta_date)}前交" if o.eta_date else ""
