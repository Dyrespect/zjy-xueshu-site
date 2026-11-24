"""运维节点的输入输出（Pydantic v2）。说明卡里的 input_model / output_model 就是这些。"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Level = Literal["urgent", "today", "info"]


class Empty(BaseModel):
    """不用输入（节点自己读设置、读库）。"""
    now: datetime | None = None  # 只给测试和本机走查用：假装现在是几点


# ---------------------------------------------------------------- 健康检查

class HealthIn(BaseModel):
    external: bool = True  # 要不要连外部依赖（支付网关、DeepSeek、飞书、微信客服）
    use_cache: bool = True


class HealthItem(BaseModel):
    key: str
    label: str
    status: Literal["ok", "warn", "problem", "skipped", "off"]
    detail: str = ""
    value: float | None = None


class HealthOut(BaseModel):
    ok: bool
    checked_at: datetime
    items: list[HealthItem]


# ---------------------------------------------------------------- 计数、聚合、清理

class FlushOut(BaseModel):
    samples: int = 0
    errors: int = 0
    visitors_new: int = 0
    gauges: int = 0


class RollupOut(BaseModel):
    hours: int = 0
    rows: int = 0


class PurgeOut(BaseModel):
    deleted: dict[str, int] = Field(default_factory=dict)


# ---------------------------------------------------------------- 推送

class MessageLine(BaseModel):
    text: str
    link: str = ""  # 完整网址（https://…/admin/…）或空


class MessageSection(BaseModel):
    title: str
    lines: list[MessageLine] = Field(default_factory=list)


class OpsMessage(BaseModel):
    """一条运维消息：标题 + 几段，每段几行（可带链接）。飞书发 post 富文本，别的实现拼成纯文字。"""
    kind: Literal["alert", "resolved", "report", "test"]
    title: str
    level: Level = "info"
    sections: list[MessageSection] = Field(default_factory=list)
    dedupe_key: str = ""

    def text(self) -> str:
        out = [self.title]
        for s in self.sections:
            out.append("")
            out.append(f"【{s.title}】" if s.title else "")
            for ln in s.lines:
                out.append(f"{ln.text}  {ln.link}".rstrip() if ln.link else ln.text)
        return "\n".join(x for x in out if x is not None).strip()


class AlertMessage(OpsMessage):
    """告警消息：必须有「发生了什么、什么时候、影响什么、去哪看」，链接必须是后台页面（scripts/check.py 规矩 19）。"""
    link: str
    happened_at: datetime

    @field_validator("link")
    @classmethod
    def _admin_link(cls, v: str) -> str:
        if "/admin" not in v:
            raise ValueError("告警消息必须带后台页面链接（/admin/…）")
        return v


class SendOut(BaseModel):
    sender: str
    delivered: bool
    detail: str = ""


# ---------------------------------------------------------------- 告警

class AlertEvalOut(BaseModel):
    opened: list[str] = Field(default_factory=list)
    still_open: list[str] = Field(default_factory=list)
    resolved: list[str] = Field(default_factory=list)
    pushed: int = 0
    suppressed: int = 0
    errors: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- 日报

class ReportIn(BaseModel):
    day: str = ""  # 北京时间日期 2026-11-17；空 = 昨天
    send: bool = True  # False 只拼不发（后台预览）
    now: datetime | None = None


class ReportOut(BaseModel):
    day: str
    problems: int
    message: OpsMessage
    sent: bool = False
    detail: str = ""


# ---------------------------------------------------------------- 备份

class BackupOut(BaseModel):
    name: str = ""
    path: str = ""
    db_bytes: int = 0
    files_count: int = 0
    files_bytes: int = 0
    seconds: float = 0.0
    verify: dict[str, Any] = Field(default_factory=dict)
    weekly: bool = False
    engine: str = ""  # restic | builtin
    note: str = ""


class PruneOut(BaseModel):
    kept: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)


class DrillOut(BaseModel):
    backup: str = ""
    integrity: str = ""
    checks: list[dict[str, Any]] = Field(default_factory=list)  # [{key,label,expected,actual,ok}]
    files_ok: bool = False
    alembic: str = ""
    seconds: float = 0.0
    error: str = ""


class LifecycleOut(BaseModel):
    rows: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
