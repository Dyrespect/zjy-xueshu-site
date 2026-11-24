"""图库节点的输入输出（不是节点文件，节点可以 import；07 设计第十五节卡 2、3、7、8）。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.figures.schemas import TypeRef

Caller = Literal["web", "open", "ai", "skill"]


class SearchIn(BaseModel):
    q: str = Field(min_length=1, max_length=200)
    code: str | None = Field(default=None, max_length=8)
    caller: Caller = "web"
    src: str = Field(default="", max_length=32)
    visitor: str = Field(default="", max_length=40)
    client: str = Field(default="", max_length=60)
    via: str = ""
    event: str = ""


class FindIn(BaseModel):
    """插件（开放接口、MCP、skill 在线模式）三个外壳共用的入参。"""

    op: Literal["find", "types", "figure"] = "find"
    q: str = Field(default="", max_length=200)
    code: str | None = Field(default=None, max_length=8)
    id: int | None = None
    n: int = Field(default=12, ge=1, le=20)
    caller: Literal["open", "ai", "skill"] = "open"
    client: str = Field(default="", max_length=60)
    via: str = ""
    event: str = ""


class FindItem(BaseModel):
    id: int
    what: str
    type_code: str
    type_name: str
    journal: str
    year: str
    cite: str  # 复制出处那一行（没有出处的图不返回）
    preview_url: str  # 带水印的预览图（绝对地址）
    thumb_url: str
    page_url: str  # 网站上的详情页（带 from，算得出插件带来几个人）


class FindOut(BaseModel):
    op: str
    query: str = ""
    guess: str = ""  # 猜的图型名
    items: list[FindItem] = []
    types: list[TypeRef] = []
    more_url: str = ""  # 网站上同一句话的搜索结果
    note: str = ""  # 每次返回末尾那行（全量图库和做汇报 PPT 的入口）


class ContributeIn(BaseModel):
    kind: Literal["tag_fix", "takedown"]
    figure_id: int | None = None
    reason: str = Field(default="", max_length=32)
    note: str = Field(default="", max_length=2000)
    query: str = Field(default="", max_length=300)
    search_id: int | None = None
    proposed: dict[str, Any] = {}
    credit: str = Field(default="", max_length=40)
    figures_text: str = Field(default="", max_length=2000)
    holder: str = Field(default="", max_length=200)
    contact: str = Field(default="", max_length=200)
    ip: str = Field(default="", max_length=64)
    via: str = ""
    event: str = ""


class ContributeOut(BaseModel):
    id: int
    kind: str
    message: str
    deadline_at: str = ""  # 版权下架：最晚什么时候处理完


class CurateIn(BaseModel):
    kind: Literal["tag_fix", "submit", "takedown"]
    item_id: int
    decision: Literal["approve", "reject", "hide"]
    edited: dict[str, Any] = {}  # Edison 改过的「改成什么」（what / code）
    note: str = Field(default="", max_length=300)
    via: str = ""
    event: str = ""


class CurateOut(BaseModel):
    status: str  # approved / hidden / rejected
    override_ids: list[int] = []
    credit: str = ""
    figure_ids: list[int] = []
