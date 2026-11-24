"""每日汇报（ops.daily_report 背后的实现）：一条消息，短，分段；几段、什么顺序在 report.json（数据）。

Edison 11-18：「日常每天给我汇报一下今天的网站运行情况有没有问题，然后以及我们收集了多少新的建议之类的，然后我再自己去处理」。
11-19 改成每晚 21:00（设置里改）汇报当天：12 点以后发的汇报当天，12 点以前发的汇报前一天；下面的「{day}」就是今天或昨天。
- problems 有没有要你处理的问题：开着的告警 + 现在健康检查有问题的项；**没有就写「一切正常」，这一段永远在**（scripts/check.py 规矩 19）。
- look {day}的单和需要你看一眼的（11-19，Edison：只推要他动手的，其余进日报）：新客户、认领、开工、交付、完成各几单（从事件表数，
  report.json 的 counts）；没单独推的通知（推满了每小时上限、没推出去、digest 级别的）按类别归拢，每类最新几条带后台链接
  （app/core/notify_policy.py 的 core_notify_items）。
- site {day}网站运行：可用性（有心跳的分钟）、请求数和出错数、p95、最慢的接口、水印队列、做单、磁盘、证书、备份。
- business {day}业务数据：访问、下单、付款、认领、交水印版、确认收货、退款、开票申请（完整的业务周报归财务成本评估模块，这里只放几个数）。
- suggestions 新收集的建议：图库标签反馈、提需求、投图、网站意见各几条、最新几条标题（交付页的修改意见不算建议，不在这里）。
- todo 待处理事项：待开票、待核对订单号、待贴文案、超时没交的单……各几条，带后台链接。
业务读数（建议、待处理、仪表）走接口位 sources，运维不 import 业务模块。
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.notify_policy import STATUS_LABELS, look_items
from app.ops import sources, stats
from app.ops.alerts import page_of
from app.ops.config import LEVEL_LABELS, OpsConfig, report_counts, report_sections
from app.ops.health import backup_state
from app.ops.models import OpsAlert
from app.ops.models_io import HealthOut, MessageLine, MessageSection, OpsMessage
from app.ops.runtime import OpsCtx

WEEKDAYS = "一二三四五六日"
# 健康检查的项 → 管它的告警规则（这条告警开着就不在日报里重复列）
HEALTH_RULE = {"db_write": "db_unwritable", "disk": "disk_usage", "cert": "cert_expiring", "backup": "backup_failed",
               "ext": "external_down", "watermark": "watermark_backlog"}


def _n(x: Any) -> str:
    return "—" if x is None else f"{x:,}" if isinstance(x, int) else str(x)


def _ms(x: float | None) -> str:
    return "—" if x is None else f"{x / 1000:.1f} 秒" if x >= 1000 else f"{x:.0f} 毫秒"


class Report:
    def __init__(self, db: Session, ctx: OpsCtx, cfg: OpsConfig, day: date, health: HealthOut | None) -> None:
        self.db, self.ctx, self.cfg, self.day, self.health = db, ctx, cfg, day, health
        self.tz = ctx.osettings.OPS_TIMEZONE
        self.start, self.end = stats.local_day_bounds(day, self.tz)
        self.problems = 0
        today = ctx.now().astimezone(ZoneInfo(self.tz)).date()
        self.dword = "今天" if day == today else "昨天" if day == today - timedelta(days=1) else f"{day.month}-{day.day}"

    def link(self, path: str) -> str:
        return self.ctx.admin_url(path)

    # ---------------------------------------------------------------- 各段

    def problems_section(self) -> list[MessageLine]:
        lines: list[MessageLine] = []
        alerts = list(self.db.scalars(select(OpsAlert).where(OpsAlert.status == "open").order_by(OpsAlert.first_at)))
        for a in alerts:
            if a.level == "info":
                continue
            lines.append(MessageLine(text=f"[{LEVEL_LABELS.get(a.level, a.level)}] {a.title}：{a.detail}", link=self.link(a.link)))
        seen = {a.rule for a in alerts}
        for i in (self.health.items if self.health else []):
            if i.status == "problem" and HEALTH_RULE.get(i.key.split(":")[0]) not in seen:
                lines.append(MessageLine(text=f"[健康检查] {i.label}：{i.detail}", link=self.link("/admin/ops?tab=overview")))
        resolved = list(self.db.scalars(select(OpsAlert).where(OpsAlert.status == "resolved", OpsAlert.first_at >= self.start,
                                                               OpsAlert.first_at < self.end)))
        self.problems = len(lines)
        if not lines:
            lines.append(MessageLine(text="一切正常，没有要你处理的。"))
        if resolved:
            names = "、".join(dict.fromkeys(a.title for a in resolved))
            lines.append(MessageLine(text=f"{self.dword}出过、已经自己恢复的：{names}（共 {len(resolved)} 次）", link=self.link("/admin/ops?tab=errors")))
        return lines

    def look_section(self) -> list[MessageLine]:
        db, s, e = self.db, self.start, self.end
        parts = [f"{c['label']} {stats.count_events(db, c['event'], s, e, where=c.get('where'))}" for c in report_counts()]
        lines = [MessageLine(text="、".join(parts))] if parts else []
        groups = look_items(db, s, e, latest_n=self.cfg.report.latest_n)
        if not groups:
            lines.append(MessageLine(text="需要你看一眼的：没有（要你动手的都已经单独推过了）。"))
            return lines
        lines.append(MessageLine(text=f"需要你看一眼的（{sum(g['count'] for g in groups)} 条，没单独推）："))
        for g in groups:
            name = (g["kind"] or "其他") if g["status"] == "digest" else STATUS_LABELS[g["status"]]
            shown = "；".join(_short(text) for text, _ in g["latest"])
            more = f" 等 {g['count']} 条" if g["count"] > len(g["latest"]) else ""
            link = next((lk for _, lk in g["latest"] if lk), "/admin")
            lines.append(MessageLine(text=f"· {name}：{shown}{more}", link=self.link(link)))
        return lines

    def site_section(self) -> list[MessageLine]:
        db, s, e = self.db, self.start, self.end
        av = stats.availability(db, s, e)
        h = stats.http_summary(db, s, e)
        lines = [MessageLine(text=f"可用性 {av['ratio']:.2%}（{av['minutes']} 分钟里 {av['alive_minutes']} 分钟在线）")]
        ok_rate = f"，成功率 {1 - h['ratio_5xx']:.2%}" if h["ratio_5xx"] is not None else ""
        lines.append(MessageLine(text=f"请求 {_n(h['requests'])} 次，出错（5xx）{_n(h['errors_5xx'])} 次{ok_rate}；"
                                      f"一半请求不到 {_ms(h['p50_ms'])}，95% 不到 {_ms(h['p95_ms'])}",
                                 link=self.link("/admin/ops?tab=errors") if h["errors_5xx"] else ""))
        slow = stats.route_table(db, s, e, limit=3, min_n=5, exclude_prefixes=stats.STAFF_PREFIXES)
        if slow:
            lines.append(MessageLine(text="最慢的接口：" + "；".join(f"{r['method']} {r['route']}（{page_of(r['route'])}）95% {_ms(r['p95_ms'])}"
                                                                for r in slow)))
        gauges = stats.latest_gauges(db, within=timedelta(hours=1), now=self.ctx.now())
        wm = gauges.get("watermark.rendering")
        made = stats.count_events(db, "delivery.watermarked", s, e)
        lines.append(MessageLine(text=f"水印出图：{self.dword}出了 {made} 版" + (f"，现在在排 {wm['value']:.0f} 版" if wm else "")))
        mk, wt = gauges.get("capacity.making"), gauges.get("capacity.waiting")
        started = stats.capacity_from_events(db, s, e)["started"]
        lines.append(MessageLine(text=f"做单：{self.dword}开工 {started} 单" + (f"，现在在做 {mk['value']:.0f} 单" if mk else "")
                                      + (f"、等开工 {wt['value']:.0f} 单" if wt else "")))
        for i in (self.health.items if self.health else []):
            if i.key == "disk" or i.key.startswith("cert:"):
                lines.append(MessageLine(text=f"{i.label}：{i.detail}"))
        st = backup_state(db)
        now = self.ctx.now()
        engine = {"restic": "restic", "builtin": "内置兜底，只有数据库"}
        max_age = self.cfg.rule("backup_failed")["params"]["max_age_hours"]
        if st["failed_at"] is not None and (st["done_at"] is None or st["failed_at"] > st["done_at"]):
            lines.append(MessageLine(text=f"备份：最近一次失败了（{str(st['failed'].get('error', ''))[:80]}）", link=self.link("/admin/ops?tab=backups")))
        elif st["done_at"] is not None and (now - st["done_at"]).total_seconds() <= max_age * 3600:
            lines.append(MessageLine(text=f"备份：最近一次 {st['done_at'].astimezone(ZoneInfo(self.tz)).strftime('%m-%d %H:%M')} 成功"
                                          f"（{engine.get(str(st['done'].get('engine', '')), st['done'].get('engine', ''))}）"))
        else:
            hours = f"已经 {(now - st['done_at']).total_seconds() / 3600:.0f} 小时" if st["done_at"] else "一直"
            lines.append(MessageLine(text=f"备份：{hours}没有成功的备份", link=self.link("/admin/ops?tab=backups")))
        return lines

    def business_section(self) -> list[MessageLine]:
        db, s, e = self.db, self.start, self.end
        f = {x["key"]: x for x in stats.funnel(db, s, e, self.cfg.funnel)}
        refunds = stats.count_events(db, "intake.order_voided", s, e, where={"code_action": "void"})
        parts = [f"{x['label']} {_n(x['count'])}" for x in f.values()]
        parts.insert(len(parts) - 1, f"退款作废 {refunds}")
        pay = stats.payments(db, s, e)
        lines = [MessageLine(text="；".join(parts))]
        if pay["checkouts"]:
            lines.append(MessageLine(text=f"自有网页支付成功率 {pay['success_rate']:.0%}（{pay['paid']}/{pay['checkouts']}），"
                                          f"回调验签失败 {pay['callback_invalid']} 次"))
        lines.append(MessageLine(text="（转化、成本、利润率这些看每周的周报）"))
        return lines

    def suggestions_section(self) -> list[MessageLine]:
        groups, errors = sources.collect("suggestion", self.db, self.start, self.end)
        lines = []
        total = sum(g.count for g in groups)
        if not groups:
            return [MessageLine(text="没有接上建议来源" + (f"（{'；'.join(errors)}）" if errors else ""))]
        lines.append(MessageLine(text=f"{self.dword}新收到 {total} 条：" + "、".join(f"{g.label} {g.count}" for g in groups)))
        n = self.cfg.report.latest_n
        for g in groups:
            if g.count and n:
                lines.append(MessageLine(text=f"{g.label}：" + "；".join(g.latest[:n]), link=self.link(g.link)))
        for e in errors:
            lines.append(MessageLine(text=e))
        return lines

    def todo_section(self) -> list[MessageLine]:
        groups, errors = sources.collect("todo", self.db, self.ctx.app)
        groups = [g for g in groups if g.count]
        if not groups and not errors:
            return [MessageLine(text="没有待处理的。")]
        lines = [MessageLine(text=f"{g.label} {g.count} 条" + (f"：{'；'.join(g.latest[:self.cfg.report.latest_n])}" if g.latest else ""),
                             link=self.link(g.link)) for g in groups]
        lines += [MessageLine(text=e) for e in errors]
        return lines

    # ---------------------------------------------------------------- 拼起来

    def build(self) -> OpsMessage:
        builders = {"problems": self.problems_section, "look": self.look_section, "site": self.site_section, "business": self.business_section,
                    "suggestions": self.suggestions_section, "todo": self.todo_section}
        sections = []
        for sec in report_sections():
            fn = builders.get(sec["key"])
            if fn is None:
                continue
            try:
                lines = fn()
            except Exception as e:  # noqa: BLE001  某一段出错，日报照发，那一段写原因
                lines = [MessageLine(text=f"这一段没算出来：{type(e).__name__}")]
                if sec["key"] == "problems":
                    self.problems += 1
            sections.append(MessageSection(title=sec["title"].replace("{day}", self.dword), lines=lines))
        if not sections or sections[0].title != report_sections()[0]["title"]:
            raise RuntimeError("日报第一段必须是「有没有要你处理的问题」")
        d = self.day
        head = f"有 {self.problems} 件要你处理" if self.problems else "一切正常"
        title = f"【日报】{d.month}-{d.day}（周{WEEKDAYS[d.weekday()]}）网站{head}"
        sections.append(MessageSection(title="", lines=[MessageLine(text="后台运维页：", link=self.link("/admin/ops"))]))
        return OpsMessage(kind="report", title=title, level="today" if self.problems else "info", sections=sections,
                          dedupe_key=f"report:{d.isoformat()}")


def yesterday(now: datetime, tzname: str) -> date:
    return (now.astimezone(ZoneInfo(tzname)) - timedelta(days=1)).date()


def report_day(now: datetime, tzname: str, at: str) -> date:
    """日报汇报哪一天：发送时间在 12 点以后（默认 21:00）汇报当天，12 点以前汇报前一天。"""
    local = now.astimezone(ZoneInfo(tzname))
    return local.date() if at >= "12:00" else (local - timedelta(days=1)).date()


def _short(text: str, n: int = 48) -> str:
    one = " ".join(text.split())
    return one if len(one) <= n else one[: n - 1] + "…"


def build(db: Session, ctx: OpsCtx, cfg: OpsConfig, day: date, health: HealthOut | None) -> tuple[OpsMessage, int]:
    r = Report(db, ctx, cfg, day, health)
    msg = r.build()
    return msg, r.problems
