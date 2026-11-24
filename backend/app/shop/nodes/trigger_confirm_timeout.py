"""trigger.confirm_timeout 超时自动确认。"""

from __future__ import annotations

from datetime import timedelta

from app.core.db import utcnow
from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, has_handler, register, run_node
from app.shop.models_io import TickIn, TickOut


def handler(call: NodeCall, data: TickIn) -> NodeResult:
    rt = call.ctx.shop
    now = data.now or utcnow()
    days = run_node("sku.catalog", call, {}).output.auto_confirm_days
    hours = days * 24
    since = now - timedelta(hours=hours)
    platforms = rt.settings.auto_confirm_platforms()
    waiting = run_node("order.waiting_customer", call, {"platforms": platforms, "idle_since": since}).output.order_ids
    out = TickOut(checked=len(waiting), hours=hours)
    for oid in waiting:
        r = run_node("confirm.receipt", NodeCall(call.db, call.ctx, call.by, oid), {
            "order_id": oid, "source": "auto", "evidence": {"rule": f"水印版交出后 {days} 天没回应", "idle_since": since.isoformat()}})
        (out.completed if r.exit == "completed" else out.skipped).append(oid)
    # 到期前提醒一次（模块 E 的 deliver.preview action=remind；同一版只发一次，按 remind:单:版 去重）
    lead = rt.settings.SHOP_AUTO_CONFIRM_REMIND_HOURS
    if lead and lead < hours and has_handler("deliver.preview"):
        soon = run_node("order.waiting_customer", call, {"platforms": platforms,
                                                         "idle_since": now - timedelta(hours=hours - lead)}).output.order_ids
        for oid in soon:
            if oid in waiting:
                continue
            r = run_node("deliver.preview", NodeCall(call.db, call.ctx, call.by, oid), {"order_id": oid, "action": "remind"})
            if r.exit == "reminded":
                out.reminded.append(oid)
    return NodeResult(exit="ok", output=out)


CARD = NodeCard(
    id="trigger.confirm_timeout",
    name="超时自动确认",
    description="自有渠道的单交了水印版，客人几天没回应（不提修改也不点确认收货），就当他确认收货了，接着发最终版。"
                "天数读订单中枢设置里的「自动确认天数」（Edison 定 3 天）。",
    category="触发",
    tech=["FastAPI lifespan 里的定时任务（app/shop/router.py，默认每 10 分钟）",
          "run_node：sku.catalog（天数）、order.waiting_customer（哪些单在等客人）、confirm.receipt（source=auto）、"
          "deliver.preview（action=remind，到期前提醒，模块 E 留的口）"],
    input_model=TickIn,
    output_model=TickOut,
    exits=[NodeExit(key="ok", label="扫完了（确认了几单写在输出里）", kind="ok")],
    config=["auto_confirm_days：订单中枢设置，自有渠道每交一版水印版几天没回应视为确认（3）",
            "SHOP_AUTO_CONFIRM_PLATFORMS：哪些渠道的单跑这个（web,fk,manual；还要确认来源表认 auto）",
            "SHOP_AUTO_CONFIRM_REMIND_HOURS：到期前几小时提醒客人一次（24；0 = 不提醒）",
            "SHOP_TIMER_ENABLED、SHOP_TIMER_INTERVAL_SEC：开不开、几秒跑一次"],
    emits=["无（确认收货节点记 intake.order_completed，source=auto）"],
    listens=["无"],
    replaceable=["天数、渠道都是配置；平台单也想等客人确认时，把平台加进 SHOP_AUTO_CONFIRM_PLATFORMS",
                 "提醒的话术在订单中枢设置 delivery.texts.remind（模块 E）"],
    failure="幂等：已经完成的单 confirm.receipt 不再动；哪些单在等客人（最近一版交出时间、有没有没处理完的改稿、暂停）"
            "只读订单中枢给的 order.waiting_customer，自己不拼条件。一轮出错整轮回滚，下一轮再来。",
    owner="B",
    status="要新做",
)
register(CARD, handler)
