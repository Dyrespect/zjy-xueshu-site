"""交接给 PPT 工厂：材料 + 要求.md + 聊天记录.md，两种方式（配置 HANDOFF_MODE）。

- direct（默认）：网站和工厂在同一台机器，直接在 FACTORY_INBOX/<客户昵称>/ 建文件夹写进去。
- pull：网站在服务器上、工厂在 Edison 的 Mac 上。开工时把同样的东西打成一个 zip 存进平台存储，
  记一条「待领」；Mac 上 scripts/factory_pull.py 用 FACTORY_PULL_TOKEN 来领（/api/handoffs），
  写进本机 inbox 后回执「已领」，服务器删掉 zip（材料原件还在存储里）。跨机器传东西留痕：每一步都写事件。

跟现在 inbox 的样子一样（`PPT工厂/inbox/青提/` 这种）：
- 材料用客户发来时的原文件名；
- 聊天记录.md：每条三行「昵称 / 2026年11月03日  5:44 / 内容」，条与条之间空一行；
- 要求.md：场合、时长、日期、学校、语言、页数结构，再加客户原话里的要求（一字不改）。
只写 inbox，不碰 jobs 和工厂代码。测试和联调里 FACTORY_INBOX 一律指临时目录。
接单 v2：交接的同时给制作方写一条「开单说明」（内容就是 要求.md + 材料在哪），制作方用 production_cli.py 看。
"""

from __future__ import annotations

from datetime import timedelta

import hashlib
import os
import re
import tempfile
import zipfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.events import record_event
from app.intake import clock
from app.intake.models import HANDOFF_STATUS_LABELS, Customer, FileRecord, Handoff, Message, Order
from app.intake.service import Ctx, display_name, order_files

_UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]+')
SENDER_NAMES = {"bot": "接单助手", "system": "接单助手", "edison": "Edison"}


def safe_folder_name(name: str) -> str:
    cleaned = _UNSAFE.sub("_", name).strip().strip(".")
    return cleaned[:60] or "客户"


def pick_folder(inbox: Path, name: str) -> Path:
    """同名文件夹已经有了（回头客、重名）就加日期，再重就加序号，绝不覆盖。"""
    base = safe_folder_name(name)
    cand = inbox / base
    if not cand.exists():
        return cand
    stamp = clock.today().strftime("%m-%d")
    cand = inbox / f"{base}_{stamp}"
    i = 2
    while cand.exists():
        cand = inbox / f"{base}_{stamp}_{i}"
        i += 1
    return cand


def _unique_name(used: set[str], filename: str) -> str:
    name = Path(filename).name or "文件"
    if name not in used:
        used.add(name)
        return name
    stem, suffix = Path(name).stem, Path(name).suffix
    i = 2
    while f"{stem}({i}){suffix}" in used:
        i += 1
    out = f"{stem}({i}){suffix}"
    used.add(out)
    return out


def message_line(m: Message, files: dict[int, FileRecord]) -> str:
    f = files.get(m.file_id) if m.file_id else None
    if m.kind == "text":
        return m.text
    if m.kind == "image":
        return f"[图片] {f.filename}" if f else ("[收款码]" if m.asset == "pay_qr" else "[图片]")
    if m.kind == "file":
        return f"[文件] {f.filename}" if f else "[文件]"
    if m.kind == "voice":
        return "[语音]"
    return m.text or f"[{m.kind}]"


def render_chat_log(customer: Customer, messages: list[Message], files: dict[int, FileRecord]) -> str:
    name = display_name(customer)
    blocks = []
    for m in messages:
        who = name if m.direction == "in" else SENDER_NAMES.get(m.sender, "接单助手")
        blocks.append(f"{who}\n{clock.fmt_chat_time(m.created_at)}\n{message_line(m, files)}")
    return "\n\n".join(blocks) + "\n"


def render_requirements(order: Order, materials: list[tuple[str, FileRecord]], sku_line: str = "",
                        handoff_brief: str = "", brief_card: str = "") -> str:
    """要求.md：交给工厂和制作方的那一份（开单说明就是它）。档位、页数上限、时限都是代码按货号算的。"""
    lines: list[str] = []
    if sku_line:
        lines.append(sku_line)
    lines.append(f"场合：{order.occasion or '没说'}")
    if order.title:
        lines.append(f"题目：{order.title}")
    if order.duration_min is not None:
        tail = "（客户没给，按场合默认值，客户同意了）" if order.duration_default else ""
        lines.append(f"时长：{order.duration_min} 分钟{tail}")
    else:
        lines.append("时长：没定")
    if order.paper_count:
        lines.append(f"篇数：{order.paper_count} 篇")
    if order.page_count:
        lines.append(f"客户要求的页数：{order.page_count} 页")
    if order.present_date:
        said = f"；客户原话：{order.present_date_text}" if order.present_date_text else ""
        lines.append(f"汇报日期：{order.present_date.isoformat()}（{clock.weekday_cn(order.present_date)}）{said}")
    if order.due_hours:
        lines.append(f"交付：开工后 {order.due_hours} 小时内交第一版水印版（交 pptx、讲稿和每页整页图）"
                     + ("，加急" if order.rush else ""))
    if order.eta_date:
        lines.append(f"最晚：{order.eta_date.isoformat()}（{clock.weekday_cn(order.eta_date)}）")
    if order.school:
        lines.append(f"学校：{order.school}（放校徽、统一配色）")
    if order.language:
        lines.append(f"语言：{order.language}")
    if order.structure_req:
        lines.append(f"页数 / 结构：{order.structure_req}")
    if materials:
        lines.append("材料：")
        for name, f in materials:
            lines.append(f"- {name}（{f.purpose or '用途没登记'}）")
    quotes = [q for q in (order.requirement_quotes or []) if q.strip()]
    if quotes:
        lines.append("")
        lines.append("客户原话里的要求（一字不改）：")
        lines.append("")
        lines.append("\n\n".join(quotes))
    if brief_card.strip() or handoff_brief.strip():
        # 客人的需求和偏好放一段：这一单客人确认过的需求卡（09 需求引导）+ 老客户上次的偏好（客户记忆），不另起一份
        lines.append("")
        lines.append("客人的需求和偏好：")
        if brief_card.strip():
            lines.append(brief_card.strip())
        if handoff_brief.strip():
            lines.append("老客户（上次的偏好，客户记忆整理的）：")
            lines.append(handoff_brief.strip())
    return "\n".join(lines) + "\n"


REAL_ROOT = Path("/Users/edison/Desktop/学术汇报")


def _guard_tests(inbox: Path) -> None:
    """保险：跑测试时 FACTORY_INBOX 忘了指临时目录，绝不往真的工厂里写。"""
    if os.environ.get("PYTEST_CURRENT_TEST") and (inbox.resolve() == REAL_ROOT or REAL_ROOT in inbox.resolve().parents):
        raise RuntimeError("测试里 FACTORY_INBOX 指到了真的 学术汇报/ 目录，拒绝写")


def _materials(db: Session, order: Order) -> list[tuple[str, FileRecord]]:
    used: set[str] = {"要求.md", "聊天记录.md"}
    return [(_unique_name(used, f.filename), f) for f in order_files(db, order)]


def _texts(db: Session, customer: Customer, order: Order, materials: list[tuple[str, FileRecord]]) -> tuple[str, str]:
    messages = list(db.scalars(select(Message).where(Message.order_id == order.id).order_by(Message.created_at, Message.id)))
    file_ids = {m.file_id for m in messages if m.file_id}
    files = {f.id: f for f in db.scalars(select(FileRecord).where(FileRecord.id.in_(file_ids)))} if file_ids else {}
    from app.intake import pricing
    from app.intake.config_store import load_config

    cfg = load_config(db)
    t = cfg.tier(order.tier_key)
    addons = [a.get("key", "") for a in (order.addons or [])]
    sku_line = ""
    if order.sku:
        sku_line = f"档位：{pricing.sku_name(cfg, order.sku, addons)}"
        if t is not None:
            sku_line += f"；页数上限 {t.max_pages} 页（{cfg.page_rule_text}）"
    from app.intake import brief

    return render_chat_log(customer, messages, files), render_requirements(order, materials, sku_line, customer.handoff_brief or "",
                                                                           brief.handoff_text(db, order))


def _write_direct(ctx: Ctx, name: str, materials, chat: str, req: str) -> Path:
    inbox = Path(ctx.settings.FACTORY_INBOX)
    _guard_tests(inbox)
    inbox.mkdir(parents=True, exist_ok=True)
    folder = pick_folder(inbox, name)
    folder.mkdir(parents=False, exist_ok=False)
    for fname, f in materials:
        with ctx.storage.open(f.storage_key) as src, open(folder / fname, "xb") as dst:
            while chunk := src.read(1024 * 1024):
                dst.write(chunk)
    (folder / "聊天记录.md").write_text(chat, encoding="utf-8")
    (folder / "要求.md").write_text(req, encoding="utf-8")
    return folder


def _store_package(ctx: Ctx, order: Order, name: str, materials, chat: str, req: str) -> tuple[str, int, str]:
    """打 zip（文件放在 zip 根上，跟 inbox 文件夹里的一样），存进平台存储。返回 (存储路径, 大小, sha256)。"""
    with tempfile.TemporaryFile() as tmp:
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
            for fname, f in materials:
                with ctx.storage.open(f.storage_key) as src, zf.open(fname, "w", force_zip64=True) as dst:
                    while chunk := src.read(1024 * 1024):
                        dst.write(chunk)
            zf.writestr("要求.md", req)
            zf.writestr("聊天记录.md", chat)
        size = tmp.tell()
        tmp.seek(0)
        digest = hashlib.sha256()
        while chunk := tmp.read(1024 * 1024):
            digest.update(chunk)
        tmp.seek(0)
        key = ctx.storage.save(tmp, folder=f"handoffs/{order.id}", filename=f"{name}.zip")
    return key, size, digest.hexdigest()


def handoff_order(db: Session, ctx: Ctx, order: Order) -> Handoff:
    customer = db.get(Customer, order.customer_id)
    name = safe_folder_name(display_name(customer))
    materials = _materials(db, order)
    chat, req = _texts(db, customer, order, materials)
    mode = ctx.settings.HANDOFF_MODE
    names = [n for n, _ in materials]
    if mode == "pull":
        key, size, sha = _store_package(ctx, order, name, materials, chat, req)
        h = Handoff(order_id=order.id, mode="pull", status="ready", folder=name, files=names,
                    package_key=key, package_size=size, package_sha256=sha, created_at=utcnow())
        where = "交接包等 Mac 来领（factory_pull.py）"
    else:
        folder = _write_direct(ctx, name, materials, chat, req)
        name = folder.name
        h = Handoff(order_id=order.id, mode="direct", status="direct", folder=name, files=names, created_at=utcnow())
        where = f"材料在 inbox/{name}/"
    db.add(h)
    db.flush()

    order.started_at = utcnow()
    if order.due_hours:
        order.eta_date = (clock.local_now(order.started_at) + timedelta(hours=order.due_hours)).date()
    order.handoff_folder = name
    order.updated_at = utcnow()
    from app.intake.production import write_brief  # production 依赖 service，放这里免得循环

    write_brief(db, order, req, f"inbox/{name}/" if mode != "pull" else f"交接包等 Mac 领进 inbox（建议文件夹 {name}/）")
    record_event(db, "intake.handoff", f"order:{order.id}",
                 {"mode": mode, "handoff": h.id, "folder": name, "files": names, "size": h.package_size})
    present = f"{clock.weekday_cn(order.present_date)}汇报" if order.present_date else "汇报日没定"
    due = f"开工后 {order.due_hours} 小时内交第一版" if order.due_hours else ""
    ctx.notifier.send(
        f"{display_name(customer)} 这单开工了：{order.occasion}，{order.duration_min} 分钟，{present}，{due}。{where}",
        level="count", kind="开工", who=f"order:{order.id}")
    return h


# ---------------------------------------------------------------- pull 模式：Mac 来领

def handoff_out(h: Handoff) -> dict:
    return {
        "id": h.id, "order_id": h.order_id, "mode": h.mode, "status": h.status,
        "status_label": HANDOFF_STATUS_LABELS.get(h.status, h.status),
        "folder": h.folder, "files": h.files or [], "size": h.package_size, "sha256": h.package_sha256,
        "created_at": h.created_at, "claimed_at": h.claimed_at, "claimed_folder": h.claimed_folder,
    }


def latest_handoff(db: Session, order: Order) -> Handoff | None:
    return db.scalar(select(Handoff).where(Handoff.order_id == order.id).order_by(Handoff.id.desc()).limit(1))


def list_handoffs(db: Session, status: str = "ready", limit: int = 50) -> list[Handoff]:
    q = select(Handoff).where(Handoff.mode == "pull")
    if status != "all":
        q = q.where(Handoff.status == status)
    return list(db.scalars(q.order_by(Handoff.id).limit(limit)))


def claim_handoff(db: Session, ctx: Ctx, h: Handoff, *, folder: str, by: str = "") -> str:
    """Mac 写好了，回执「已领」。重复回执不改任何东西（断了重跑时会再报一次）。

    返回要删掉的交接包存储路径（调用方提交事务之后再 `drop_package`，免得事务没提交、包先没了）。
    """
    if h.mode != "pull":
        raise ValueError("这条是直接写入的，不用领")
    if h.status == "claimed":
        return ""
    folder = safe_folder_name(folder or h.folder)
    h.status = "claimed"
    h.claimed_folder = folder
    h.claimed_by = by[:128]
    h.claimed_at = utcnow()
    old_key, h.package_key = h.package_key, ""
    order = db.get(Order, h.order_id)
    if order is not None:
        order.handoff_folder = folder
        order.updated_at = utcnow()
    record_event(db, "intake.handoff_claimed", f"order:{h.order_id}",
                 {"handoff": h.id, "folder": folder, "by": h.claimed_by, "sha256": h.package_sha256})
    db.flush()
    customer = db.get(Customer, order.customer_id) if order is not None else None
    who = display_name(customer) if customer is not None else f"订单 {h.order_id}"
    ctx.notifier.send(f"{who} 的材料已经领到 Mac：inbox/{folder}/", level="digest", kind="材料领到 Mac", who=f"order:{h.order_id}")
    return old_key


def drop_package(ctx: Ctx, key: str) -> None:
    """领完删交接包（材料原件、聊天记录都还在平台里）。删不掉只是多占点盘，不影响回执。"""
    if not key:
        return
    try:
        ctx.storage.delete(key)
    except Exception:
        pass
