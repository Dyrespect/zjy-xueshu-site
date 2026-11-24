"""运维的设置（存在 ops_kv 的 settings 一条，后台「运维 → 设置」「飞书汇报」改）。设计第四、七节。

- retention：各种运维数据留多久（scripts/check.py 规矩 19 要求保留期只在这里，retention.py 不许写死天数）。
- push：即时推送总开关、哪些级别推、静默多久、每小时最多推几条。rules：每条告警规则的开关、推不推、阈值（覆盖 alerts.json 的默认）。
- report：日报开关、几点发、每类列最新几条。backup：备份几点、留几个日备周备、恢复演练隔几天、核对哪些数。
- lifecycle：客户数据的保存期限（我的建议，标「待法务 / 财务确认」，确认一项勾一项；发票、付款凭证不编数，留空）。
- funnel：漏斗每一步从哪数（page.uv 或 event:<事件类型>）；externals：外部服务成功率从哪两种事件数。都是数据，不写死。
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.events import record_event
from app.ops.models import OpsKV

HERE = Path(__file__).parent
LEVELS = ("urgent", "today", "info")
LEVEL_LABELS = {"urgent": "要立刻处理", "today": "今天看一下", "info": "只是记录"}
_HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


@lru_cache
def alert_rules() -> list[dict[str, Any]]:
    return json.loads((HERE / "alerts.json").read_text(encoding="utf-8"))["rules"]


@lru_cache
def report_sections() -> list[dict[str, Any]]:
    return json.loads((HERE / "report.json").read_text(encoding="utf-8"))["sections"]


def report_counts() -> list[dict[str, Any]]:
    """日报「{day}的单和需要你看一眼的」第一行数哪几样（report.json 的 counts）。"""
    return json.loads((HERE / "report.json").read_text(encoding="utf-8")).get("counts", [])


@lru_cache
def jobs() -> list[dict[str, Any]]:
    return json.loads((HERE / "jobs.json").read_text(encoding="utf-8"))["jobs"]


class Retention(BaseModel):
    model_config = ConfigDict(extra="ignore")
    raw_days: int = Field(default=30, ge=1, le=400)  # 原始（每分钟）
    hourly_days: int = Field(default=365, ge=7, le=3650)  # 小时聚合
    errors_days: int = Field(default=30, ge=1, le=400)  # 最近错误
    visitors_days: int = Field(default=2, ge=1, le=31)  # 当天访客散列
    alerts_days: int = Field(default=180, ge=7, le=3650)  # 关掉的告警
    notify_days: int = Field(default=90, ge=7, le=3650)  # 业务通知记录（core_notify_items：推了的、进日报的）


class PushCfg(BaseModel):
    model_config = ConfigDict(extra="ignore")
    enabled: bool = True  # 即时推送总开关（关了只记录，后台看）
    # 哪些级别马上推（Edison 11-19：只推要他动手的）：默认只推「要立刻处理」；「今天看一下」进当天日报第一段，info 只记录
    levels: list[str] = Field(default_factory=lambda: ["urgent"])
    silence_minutes: dict[str, int] = Field(default_factory=lambda: {"urgent": 60, "today": 360, "info": 1440})
    max_per_hour: int = Field(default=10, ge=1, le=100)  # 每小时最多推几条，多的合成一条「还有 N 条」
    notify_resolved: bool = True  # 「要立刻处理」的恢复了也说一声

    @field_validator("levels")
    @classmethod
    def _levels(cls, v: list[str]) -> list[str]:
        return [x for x in dict.fromkeys(v) if x in LEVELS]


class RuleOverride(BaseModel):
    model_config = ConfigDict(extra="ignore")
    enabled: bool = True
    push: bool = True  # 这条走即时推送
    level: Literal["urgent", "today", "info"] | None = None
    params: dict[str, float] = Field(default_factory=dict)


class ReportCfg(BaseModel):
    model_config = ConfigDict(extra="ignore")
    enabled: bool = True
    time: str = "21:00"  # 北京时间；12 点以后发的汇报当天，12 点以前发的汇报前一天
    latest_n: int = Field(default=3, ge=0, le=10)

    @field_validator("time")
    @classmethod
    def _time(cls, v: str) -> str:
        if not _HHMM.match(v):
            raise ValueError("时间写成 09:00 这样")
        return v


class VerifySpec(BaseModel):
    """备份核对数：备份时在快照上数一遍写进清单，恢复演练时在恢复出来的库上再数一遍，两边要一样。"""
    key: str
    label: str
    table: str
    agg: Literal["count", "sum_decimal", "sum_int"] = "count"
    column: str = ""


class BackupCfg(BaseModel):
    model_config = ConfigDict(extra="ignore")
    enabled: bool = True  # 本机备份（推对象存储另有开关 OPS_BACKUP_COS_ENABLED，默认关）
    time: str = "03:30"
    keep_daily: int = Field(default=7, ge=1, le=60)
    keep_weekly: int = Field(default=4, ge=0, le=52)
    weekly_weekday: int = Field(default=6, ge=0, le=6)  # 周几的那份留作周备（0 = 周一，6 = 周日）
    drill_every_days: int = Field(default=30, ge=1, le=365)
    verify: list[VerifySpec] = Field(default_factory=lambda: [
        VerifySpec(key="orders", label="订单数", table="intake_orders"),
        VerifySpec(key="paid_sum", label="订单实付合计（元）", table="intake_orders", agg="sum_decimal", column="paid_amount"),
        VerifySpec(key="checkouts_paid_fen", label="自有网页实收合计（分）", table="shop_checkouts", agg="sum_int", column="paid_fen"),
        VerifySpec(key="invoices", label="发票申请数", table="invoice_requests"),
        VerifySpec(key="files", label="文件登记数", table="intake_files"),
        VerifySpec(key="events", label="事件记录数", table="events"),
    ])

    @field_validator("time")
    @classmethod
    def _time(cls, v: str) -> str:
        if not _HHMM.match(v):
            raise ValueError("时间写成 03:30 这样")
        return v


class LifeItem(BaseModel):
    key: str
    label: str
    days: int | None = None  # None = 还没定（发票、付款凭证：待财务确认，不编数）
    how: str = ""  # 到期怎么处理
    confirm_by: str = "法务"  # 待谁确认


def _default_lifecycle() -> list[LifeItem]:
    return [
        LifeItem(key="materials", label="客户材料（论文、开题报告、数据）", days=90,
                 how="订单已交付满这么多天后删除文件，留文件名和大小（我的建议）", confirm_by="法务"),
        LifeItem(key="watermark", label="水印图、整页底图", days=90, how="订单已交付满这么多天后删除（我的建议）", confirm_by="法务"),
        LifeItem(key="finals", label="最终版（PPT、讲稿）", days=180, how="订单已交付满这么多天后删除，客人要再下载找负责人（我的建议）",
                 confirm_by="法务"),
        LifeItem(key="chat", label="聊天记录", days=365, how="最后一条消息满这么多天后删正文、留条数（我的建议）", confirm_by="法务"),
        LifeItem(key="invoices", label="发票文件和开票信息", days=None, how="待财务确认（不编数）", confirm_by="财务"),
        LifeItem(key="payments", label="付款记录、支付通知、退款记录", days=None, how="待财务确认（不编数）", confirm_by="财务"),
        LifeItem(key="events", label="事件记录（平台申诉凭据）", days=None, how="先一直留；要不要定期限待法务确认", confirm_by="法务"),
    ]


class FunnelStep(BaseModel):
    key: str
    label: str
    source: str  # page.uv | event:<事件类型>


class ExternalFromEvents(BaseModel):
    key: str
    label: str
    ok: str  # 成功一次记的事件
    fail: str  # 失败一次记的事件


def _default_funnel() -> list[FunnelStep]:
    return [
        FunnelStep(key="visit", label="访问（独立访客）", source="page.uv"),
        FunnelStep(key="checkout", label="下单（自有网页）", source="event:shop.checkout_created"),
        FunnelStep(key="paid", label="付款（全部渠道）", source="event:intake.order_created"),
        FunnelStep(key="claimed", label="认领", source="event:intake.order_claimed"),
        FunnelStep(key="delivered", label="交水印版", source="event:delivery.proof_published"),
        FunnelStep(key="completed", label="确认收货", source="event:intake.order_completed"),
        FunnelStep(key="invoice", label="开票申请", source="event:invoice.submitted"),
    ]


def _default_externals() -> list[ExternalFromEvents]:
    return [
        ExternalFromEvents(key="deepseek", label="DeepSeek（助手回消息）", ok="intake.bot_run", fail="intake.bot_failed"),
        ExternalFromEvents(key="send", label="给客人发消息（微信客服等）", ok="intake.message_sent", fail="intake.send_failed"),
        ExternalFromEvents(key="pay", label="支付下单（网关）", ok="shop.checkout_created", fail="shop.checkout_failed"),
        ExternalFromEvents(key="feishu", label="飞书推送", ok="ops.sent", fail="ops.send_failed"),
    ]


class OpsConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    retention: Retention = Field(default_factory=Retention)
    push: PushCfg = Field(default_factory=PushCfg)
    rules: dict[str, RuleOverride] = Field(default_factory=dict)
    report: ReportCfg = Field(default_factory=ReportCfg)
    backup: BackupCfg = Field(default_factory=BackupCfg)
    lifecycle: list[LifeItem] = Field(default_factory=_default_lifecycle)
    lifecycle_confirmed: list[str] = Field(default_factory=list)  # 法务 / 财务已确认的保存期限（LifeItem.key）
    thresholds_confirmed: bool = False  # Edison 看过阈值了
    funnel: list[FunnelStep] = Field(default_factory=_default_funnel)
    externals: list[ExternalFromEvents] = Field(default_factory=_default_externals)

    @field_validator("rules")
    @classmethod
    def _rules_known(cls, v: dict[str, RuleOverride]) -> dict[str, RuleOverride]:
        known = {r["id"] for r in alert_rules()}
        return {k: o for k, o in v.items() if k in known}

    def rule(self, rule_id: str) -> dict[str, Any]:
        """一条规则合上设置之后的样子：{id, title, level, link, impact, params, enabled, push}。"""
        base = next((r for r in alert_rules() if r["id"] == rule_id), None)
        if base is None:
            raise KeyError(rule_id)
        o = self.rules.get(rule_id, RuleOverride())
        params = {**base.get("params", {}), **{k: v for k, v in o.params.items() if k in base.get("params", {})}}
        return {**base, "params": params, "enabled": o.enabled, "push": o.push, "level": o.level or base["level"]}

    def all_rules(self) -> list[dict[str, Any]]:
        return [self.rule(r["id"]) for r in alert_rules()]


def load_config(db: Session) -> OpsConfig:
    row = db.get(OpsKV, "settings")
    return OpsConfig.model_validate(row.value if row is not None else {})


def save_config(db: Session, data: dict[str, Any], *, by: str) -> OpsConfig:
    """校验后存；记 ops.config_changed（改了哪几块）。调用方提交。"""
    before = load_config(db)
    cfg = OpsConfig.model_validate({**before.model_dump(), **data})
    changed = [k for k, v in cfg.model_dump().items() if before.model_dump().get(k) != v]
    row = db.get(OpsKV, "settings")
    if row is None:
        row = OpsKV(key="settings")
        db.add(row)
    row.value, row.updated_at = cfg.model_dump(), utcnow()
    record_event(db, "ops.config_changed", "ops:settings", {"fields": changed, "by": by})
    return cfg


def kv_get(db: Session, key: str) -> dict[str, Any]:
    row = db.get(OpsKV, key)
    return dict(row.value) if row is not None and row.value else {}


def kv_set(db: Session, key: str, value: dict[str, Any]) -> None:
    row = db.get(OpsKV, key)
    if row is None:
        row = OpsKV(key=key)
        db.add(row)
    row.value, row.updated_at = value, utcnow()
