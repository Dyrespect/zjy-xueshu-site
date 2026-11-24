"""聚人节点的输入输出、对外接口的入参出参（不是节点文件，节点可以 import）。对外的返回里没有任何文件路径。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

VISITOR = r"^[A-Za-z0-9_-]{8,40}$"
Placement = Literal["header", "nav", "home", "results", "detail", "unlock_done", "pack", "ai", "skill", "footer", "plugin"]


# ---- funnel.track ----
class VisitIn(BaseModel):
    visitor: str = Field(pattern=VISITOR)
    landing: str = Field(default="/", max_length=300)
    src: str = Field(default="", max_length=32)  # 链接里的 from
    share: str = Field(default="", max_length=12)  # 链接里的 s（分享码）
    referrer_host: str = Field(default="", max_length=100)
    ip: str = Field(default="", max_length=64)
    via: str = ""
    event: str = ""


class VisitOut(BaseModel):
    visitor: str
    src: str
    counted: bool
    share_new: bool = False  # 这次给分享码 +1 了（转发链接带来的新访客）
    share_unlock_id: int | None = None


# ---- funnel.cta ----
class CtaIn(BaseModel):
    placement: Placement
    target: Literal["order", "site", "gzh"]
    visitor: str = Field(default="", max_length=40)
    record: bool = False  # True = 记一次点击
    via: str = ""
    event: str = ""


class CtaOut(BaseModel):
    url: str  # 空 = 这个目标没有网址（公众号）
    text: str


# ---- figure.unlock_request ----
class UnlockIn(BaseModel):
    visitor: str = Field(pattern=VISITOR)
    src: str = Field(default="", max_length=32)
    ip: str = Field(default="", max_length=64)
    via: str = ""
    event: str = ""


class UnlockOut(BaseModel):
    unlock_id: int
    share_code: str
    created: bool


# ---- figure.unlock_verify（流程里一进「核验」就跑）----
class VerifyIn(BaseModel):
    subject_id: int
    subject_type: str = "figure_unlock"
    evidence_id: int | None = None
    via: str = ""
    event: str = ""


class VerifyOut(BaseModel):
    verdict: Literal["pass", "need_more", "wait_admin", "fail"]
    verifier: str
    reason: str


# ---- figure.pack_deliver（流程里一进「发链接」就跑）----
class DeliverIn(BaseModel):
    subject_id: int
    subject_type: str = "figure_unlock"
    via: str = ""
    event: str = ""


class DeliverOut(BaseModel):
    pack_version: str = ""
    tier: str = "full"
    grant_id: int | None = None


# ---- figure.release（后台贴网盘链接，这一版上线）----
class ReleaseIn(BaseModel):
    version: str = Field(min_length=4, max_length=16, pattern=r"^[0-9A-Za-z._-]+$")
    tier: Literal["full", "lite"]
    url: str = Field(min_length=10, max_length=500)
    extract_code: str = Field(default="", max_length=16)
    provider: Literal["baidu", "quark", "aliyun", "cos_signed", "other"] = "baidu"
    count: int = Field(default=0, ge=0, le=100000)
    size_mb: float = Field(default=0, ge=0, le=1_000_000)
    manifest_sha256: str = Field(default="", max_length=64)
    note: str = Field(default="", max_length=200)
    via: str = ""
    event: str = ""


class ReleaseOut(BaseModel):
    pack_id: int
    active: bool
    resent: int = 0  # 卡在「还没贴链接」的，这次自动补发了几个


# ---- skill.oss_sync（只登记说明卡，Mac 上跑 scripts/skill_export.py）----
class SyncIn(BaseModel):
    direction: Literal["export", "import"]
    version: str
    dry_run: bool = True


class SyncOut(BaseModel):
    files: list[str] = []
    blocked: list[str] = []


# ---- 对外接口 ----
class UnlockView(BaseModel):
    """「要全部图库？」弹层看到的：到哪一步了、他的链接带来几个人、核验结论；只有已发才有网盘那段话。"""

    share_code: str
    share_text: str
    stage: str
    stage_label: str
    verifier: str  # 现在用的核验方式
    reason: str  # 上一次核验说了什么（再交一张、等负责人看……）
    share_visits: int
    need_visits: int  # share_visits 核验要几个；别的方式是 0
    pack_text: str  # 只有「已发链接」才有；没核验过永远是空的
    pack_version: str
    follow_note: str
    gzh_name: str
    gzh_keyword: str


class UnlockStartIn(BaseModel):
    visitor: str = Field(pattern=VISITOR)
    src: str = Field(default="", max_length=32)


class VisitorIn(BaseModel):
    visitor: str = Field(pattern=VISITOR)


class CtaClickIn(BaseModel):
    placement: Placement
    target: Literal["order", "site", "gzh"]
    visitor: str = Field(default="", max_length=40)


# ---- 插件（开放接口、MCP）对外的返回：和 figure.ai_tool 的输出一一对应，接口自己留一份契约（不 import figures）----
class OpenItem(BaseModel):
    id: int
    what: str
    type_code: str
    type_name: str
    journal: str
    year: str
    cite: str
    preview_url: str
    thumb_url: str
    page_url: str


class OpenType(BaseModel):
    code: str
    name: str


class OpenFindOut(BaseModel):
    op: str
    query: str = ""
    guess: str = ""
    items: list[OpenItem] = []
    types: list[OpenType] = []
    more_url: str = ""
    note: str = ""
