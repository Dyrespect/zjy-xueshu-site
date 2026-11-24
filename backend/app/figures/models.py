"""图库的表：反馈、需求、投图、对网站的意见，搜索记录和点击（PRD 第六节）；
版权下架、叠在索引上的改标签和下架（模块 L，docs/任务单/07_科研绘图聚人_设计.md 第八节）。

四张「收东西」的表共用几列：什么时候、谁（IP，限流用）、状态（new 没处理 / done 处理了）、
Edison 写的一句备注、什么时候处理的。上传的图走 core/storage，库里只存它返回的相对路径
（只在后台按号取图时用，不出现在任何接口返回里）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UTCDateTime, utcnow

STATUS_NEW = "new"
STATUS_DONE = "done"
# 审核结论（figure.curate）：改标签、投图、版权下架都用这一套
DECISION_NEW = "new"
DECISION_APPROVED = "approved"
DECISION_REJECTED = "rejected"
DECISION_HIDDEN = "hidden"


class _Inbox:
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    ip: Mapped[str] = mapped_column(String(64), default="", index=True)
    status: Mapped[str] = mapped_column(String(16), default=STATUS_NEW, index=True)
    admin_note: Mapped[str] = mapped_column(Text, default="")
    handled_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class FigureFeedback(_Inbox, Base):
    """「标签不对 / 这张不相关」：挂在某张图上。可以直接写「改成什么」和署名（模块 L，figure.contribute）。"""

    __tablename__ = "figure_feedback"
    figure_id: Mapped[int] = mapped_column(Integer, index=True)
    reason: Mapped[str] = mapped_column(String(32))
    note: Mapped[str] = mapped_column(Text, default="")
    query: Mapped[str] = mapped_column(String(300), default="")  # 当时搜的那句话
    search_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    proposed: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)  # {"what": 讲的是什么, "code": 图型}
    credit: Mapped[str] = mapped_column(String(40), default="")  # 署名，审过后详情页写「标签由 XX 改过」
    decision: Mapped[str] = mapped_column(String(16), default=DECISION_NEW, index=True)  # new / approved / rejected


class FigureRequest(_Inbox, Base):
    """提需求：想画什么图，找不到。"""

    __tablename__ = "figure_requests"
    want: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(Text, default="")
    contact: Mapped[str] = mapped_column(String(200), default="")
    sketch: Mapped[str] = mapped_column(String(500), default="")  # 上传的草图（storage 相对路径）
    query: Mapped[str] = mapped_column(String(300), default="")
    search_id: Mapped[int | None] = mapped_column(Integer, nullable=True)


class FigureSubmission(_Inbox, Base):
    """投图：进后台待审，不直接上库。"""

    __tablename__ = "figure_submissions"
    image: Mapped[str] = mapped_column(String(500))  # 上传的图（storage 相对路径）
    source: Mapped[str] = mapped_column(Text)  # DOI 或论文题目
    reason: Mapped[str] = mapped_column(Text, default="")
    credit: Mapped[str] = mapped_column(String(100), default="")  # 署名，收录后显示「由 XX 推荐」
    decision: Mapped[str] = mapped_column(String(16), default=DECISION_NEW, index=True)  # new / approved / rejected


class SiteFeedback(_Inbox, Base):
    """对网站本身的意见。"""

    __tablename__ = "site_feedback"
    content: Mapped[str] = mapped_column(Text)
    contact: Mapped[str] = mapped_column(String(200), default="")
    page: Mapped[str] = mapped_column(String(300), default="")


class FigureTakedown(_Inbox, Base):
    """版权方要求删除（页脚「版权问题」）：48 小时内从网站和下一版图库包里撤（07 设计第六节第 7 条）。"""

    __tablename__ = "figure_takedowns"
    figure_ids: Mapped[list[Any]] = mapped_column(JSON, default=list)  # 从「哪几张图」里认出来的号
    figures_text: Mapped[str] = mapped_column(Text, default="")  # 原话：图的网址或号
    holder: Mapped[str] = mapped_column(String(200), default="")  # 权利人（期刊、出版社、作者）
    contact: Mapped[str] = mapped_column(String(200), default="")
    reason: Mapped[str] = mapped_column(Text, default="")
    deadline_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)  # 收到 + 48 小时
    decision: Mapped[str] = mapped_column(String(16), default=DECISION_NEW, index=True)  # new / hidden / rejected


class FigureOverride(Base):
    """叠在索引上的一层：审过的改标签（what / code）和下架（hidden）。网站读时合并，索引文件不动。"""

    __tablename__ = "figure_overrides"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    figure_id: Mapped[int] = mapped_column(Integer, index=True)
    field: Mapped[str] = mapped_column(String(16))  # what / code / hidden
    value: Mapped[Any] = mapped_column(JSON, default=None)
    credit: Mapped[str] = mapped_column(String(40), default="")
    source_kind: Mapped[str] = mapped_column(String(16), default="")  # feedback / takedown / admin
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)


class SearchLog(Base):
    """每次搜索：问了什么、猜的图型、拆出的词、每组几张、有没有 0 张的词。"""

    __tablename__ = "search_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    query: Mapped[str] = mapped_column(String(300))
    guess: Mapped[str] = mapped_column(String(8), default="")  # 猜的图型；猜不出空
    code: Mapped[str] = mapped_column(String(8), default="")  # 实际用的（图型或「任意」）
    overridden: Mapped[bool] = mapped_column(Boolean, default=False)  # 用户在下拉里改过图型
    words: Mapped[list[Any]] = mapped_column(JSON, default=list)
    zero_words: Mapped[list[Any]] = mapped_column(JSON, default=list)
    groups: Mapped[list[Any]] = mapped_column(JSON, default=list)  # [{"key", "title", "n"}]
    total: Mapped[int] = mapped_column(Integer, default=0)
    used_vectors: Mapped[bool] = mapped_column(Boolean, default=False)
    took_ms: Mapped[int] = mapped_column(Integer, default=0)
    # 谁来搜的（模块 L）：web 网站 / open 开放接口 / ai 插件 / skill 在线模式；从哪来；哪个访客；AI 客户端名
    caller: Mapped[str] = mapped_column(String(8), default="web", server_default="web", index=True)
    src: Mapped[str] = mapped_column(String(32), default="", server_default="")
    visitor: Mapped[str] = mapped_column(String(40), default="", server_default="")
    client: Mapped[str] = mapped_column(String(60), default="", server_default="")


class SearchClick(Base):
    """结果页上点了哪张。"""

    __tablename__ = "search_clicks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    search_id: Mapped[int] = mapped_column(ForeignKey("search_logs.id", ondelete="CASCADE"), index=True)
    figure_id: Mapped[int] = mapped_column(Integer, index=True)
    position: Mapped[int] = mapped_column(Integer, default=0)
    lane: Mapped[str] = mapped_column(String(64), default="")
