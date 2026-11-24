"""入口的固定话术（entry.notice 节点背后的实现）：认领结果、资料清单、上限提醒、去平台点确认收货……

- 模板在订单中枢的设置 `entry_texts`（契约第二节第 6 条，后台能改）；设置里没有的几句用这里的默认值。
- 不调模型、不写价格（检查 10 管价格数字）；认领、清单这类一字不改原样发。
- 一条装得下：微信客服一条最多 2048 字节，超了先删选填项说明，再不行改发短版 + 交付页链接。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.intake import clock, pricing
from app.intake.config_store import DEFAULT_CONFIG, BizConfig, load_config
from app.intake.models import STAGE_LABELS, Order

# 设置 entry_texts 里没有的（我写的，标「我的建议」，后台能在 entry_texts 里加同名的覆盖）
EXTRA_TEXTS: dict[str, str] = {
    "claim_addon_ok": "加购好了：{sku_name}，已经挂到你这单（{order_sku}）上。",
    "claim_expired": "这枚激活码过期了。有疑问可以问我，或者发「找负责人」。",
    "claim_wrong": "这枚激活码现在用不上：{detail}。有疑问发「找负责人」。",
    "claim_short": "已对上你的订单：{sku_name}（激活码尾号 {last4}）。要交的资料看这里：{url}",
    "error": "我这边出了点问题，稍后回你。",
    "welcome_with_intro": "想先自己看看我们做什么、多少钱：{intro_url}",
    # 需求卡（09 需求引导）：认领那句话后面接一句、2 小时没确认提醒一次、负责人改了发回去
    "brief_invite": "先花一分钟把这次要什么点选一下（不用打字，确认了才开工）：{brief_url}",
    "brief_remind": "需求确认卡还没确认哦：点开看一眼，对就点「对，开工」，确认了我们才开工。{brief_url}",
    "brief_sent_back": "按你说的改了需求卡{note}，再看一眼，对就点「对，开工」：{brief_url}",
}

CUSTOMER_PROGRESS: dict[str, str] = {
    "paid": "等你认领",
    "claimed": "等你发资料",
    "making": "在做了",
    "completed": "已完成，可编辑的 PPT 和讲稿马上发",
    "delivered": "可编辑的 PPT 和讲稿发了",
    "void": "这单作废了",
}


def text(cfg: BizConfig, key: str, **kw: Any) -> str:
    """设置 entry_texts → 订单中枢的默认值 → 这里的默认值。占位符缺了不报错。"""
    t = cfg.entry_texts.get(key) or DEFAULT_CONFIG["entry_texts"].get(key) or EXTRA_TEXTS.get(key, "")
    try:
        return t.format(**kw) if kw else t
    except (KeyError, IndexError):
        return t


def last4(code: str) -> str:
    return code[-4:] if code else ""


def hours_for(cfg: BizConfig, order: Order) -> int | None:
    """开工后几小时内交第一版：标准时限；付了加急（档位开了加急）用加急时限；帮我找文献再加几小时。"""
    t = cfg.tier(order.tier_key)
    if t is None:
        return None
    keys = {a.get("key", "") for a in (order.addons or [])}
    return pricing.promised_hours(cfg, t, rush="rush" in keys and t.rush, find_refs="find_refs" in keys)  # 对客承诺，含余量


def checklist_lists(db: Session, order: Order, collect: Any | None) -> dict[str, str]:
    """认领那句话（claim_ok）的资料清单占位符：{materials} 分行写好的整段（场合知道就列这个场合要的，不知道就按场合列主材料
    再问场合），{required_list} / {optional_list} 给后台改过的旧模板用。字全从设置里的资料清单来（app/intake/materials.py）。"""
    from app.intake import materials
    from app.intake.rules import received_purposes
    from app.intake.service import order_facts

    cfg = load_config(db)
    facts = order_facts(db, order)
    done = {it.key for it in collect.items if it.done} if collect is not None else set()
    return materials.claim_parts(cfg, occasion=order.occasion, find_refs=facts.find_refs, have=received_purposes(facts),
                                 done_keys=done, req_keys=materials.required_keys(cfg, facts.sku, facts.addons))


def customer_progress(order: Order, collect: Any | None = None) -> str:
    """给客人看的进度（兑换页、claim_yours）；后台看的细一层在 orders.progress。"""
    st = order.stage
    if st == "collecting":
        if order.queued_at and order.start_date:
            return f"资料齐了，排在 {clock.fmt_date(order.start_date)}开工"
        if collect is not None and collect.ask_text:
            return f"还在收资料（{collect.ask_text}）"
        return "还在收资料"
    if st == "watermarked":
        return f"第 {order.delivery_round} 版水印版交了，等你看"
    if st == "revising":
        return f"在改第 {order.delivery_round} 版"
    return CUSTOMER_PROGRESS.get(st, STAGE_LABELS.get(st, st))


def next_step(order: Order, collect: Any | None, delivery_url: str) -> str:
    st = order.stage
    if st in ("claimed", "collecting") and collect is not None and collect.ask_text and not order.queued_at:
        return f"{collect.ask_text}，直接发我就行。"
    if st in ("watermarked", "revising", "completed", "delivered"):
        return f"成品在这个页面：{delivery_url}"
    return ""


def fit_bytes(full: str, short: str, limit: int | None) -> tuple[str, bool]:
    """一条装得下就发全的；装不下发短的。返回（文字，是不是改成了短版）。"""
    if limit is None or len(full.encode("utf-8")) <= limit:
        return full, False
    return short, True


def sku_name_of(cfg: BizConfig, order: Order) -> str:
    return pricing.sku_name(cfg, order.sku, [a.get("key", "") for a in (order.addons or []) if a.get("by") == "bundle"]) \
        if order.sku else "货号没定"
