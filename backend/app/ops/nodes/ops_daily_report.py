"""ops.daily_report 每日汇报。"""

from __future__ import annotations

from datetime import date

from app.core.events import record_event
from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register, run_node
from app.ops import health, report
from app.ops.config import kv_set, load_config
from app.ops.models_io import ReportIn, ReportOut


def handler(call: NodeCall, data: ReportIn) -> NodeResult:
    db, ctx = call.db, call.ctx
    cfg = load_config(db)
    now = data.now or ctx.now()
    day = date.fromisoformat(data.day) if data.day else report.report_day(now, ctx.osettings.OPS_TIMEZONE, cfg.report.time)
    h = health.run(db, ctx, cfg, external=False, use_cache=True)
    msg, problems = report.build(db, ctx, cfg, day, h)
    out = ReportOut(day=day.isoformat(), problems=problems, message=msg)
    if not data.send:
        return NodeResult(exit="skipped", output=out, detail="只预览，没发")
    r = run_node("ops.send", call, msg)
    out.sent = r.exit == "sent"
    out.detail = r.detail
    kv_set(db, "last_report", {"day": out.day, "title": msg.title, "sent": out.sent, "at": now.isoformat(), "detail": r.detail[:200]})
    record_event(db, "ops.report_sent" if out.sent else "ops.report_not_sent", f"ops:report:{out.day}",
                 {"problems": problems, "sender_exit": r.exit, "by": call.by})
    return NodeResult(exit="sent" if out.sent else ("skipped" if r.exit == "skipped" else "fail"), output=out, detail=r.detail)


CARD = NodeCard(
    id="ops.daily_report",
    name="每日汇报",
    description="每晚 21:00（设置里改；12 点以前发就汇报前一天）在飞书发一条当天的汇报：有没有要你处理的问题（没有就写「一切正常」）、"
                "当天的单（新客户、认领、开工、交付、完成）和没单独推的通知（需要你看一眼的）、网站运行（可用性、出错、最慢的接口、"
                "水印队列、做单、磁盘、证书、备份）、业务数（访问、下单、付款、认领、交付、确认收货、退款、开票申请）、新收集的建议"
                "（图库标签反馈、提需求、投图、网站意见）、待处理事项（待开票、待核对订单号、待贴文案、超时没交的单），都带后台链接。",
    category="运营",
    tech=["report.json（几段、什么顺序，数据）", "SQLAlchemy（events、ops_samples、ops_alerts、core_notify_items）", "接口位 sources.suggestion / sources.todo",
          "run_node(\"ops.send\")"],
    input_model=ReportIn,
    output_model=ReportOut,
    exits=[NodeExit(key="sent", label="发出去了", kind="ok"), NodeExit(key="skipped", label="只预览 / 没配机器人", kind="ok"),
           NodeExit(key="fail", label="没发出去", kind="fail")],
    config=["report.enabled、report.time（默认 21:00，北京时间）、report.latest_n（每类列最新几条）", "funnel（业务数从哪几种事件数）",
            "report.json 的 counts（当天的单数哪几样）"],
    emits=["ops.report_sent", "ops.report_not_sent", "ops.sent（推送节点记）"],
    listens=["无"],
    replaceable=["业务数的完整版：财务成本评估模块的 eval.weekly 周报（这里只放几个数）"],
    failure="某一段算不出来，那一段写「没算出来：原因」，日报照发；第一段「有没有问题」永远在。同一天调度只跑一次（ops_kv 记着），"
            "后台「现在发」可以手动重发。",
    owner="运维",
    status="要新做",
)
register(CARD, handler)
