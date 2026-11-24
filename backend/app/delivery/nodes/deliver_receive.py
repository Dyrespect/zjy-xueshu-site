"""deliver.receive 收成品包。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.core.db import lock_row
from app.core.events import record_event
from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.delivery import versions
from app.delivery.checks import CheckFailed
from app.intake import service
from app.intake.models import Order


class PackageIn(BaseModel):
    order_id: int
    note: str = Field(default="", max_length=2000, description="制作方的一句说明")
    source: Literal["maker_cli", "admin_upload", "api"] = Field(default="maker_cli", description="谁交的：制作方命令行 / 后台人工上传 / 以后的做单进程")
    revision_id: int | None = Field(default=None, description="回应哪张改稿单（可空）")


class PackageOut(BaseModel):
    order_id: int = 0
    round: int
    stage: str
    slide_count: int = 0
    page_count: int = 0
    final_file_ids: list[int] = Field(default_factory=list)
    version_id: int | None = None


def handler(call: NodeCall, data: PackageIn) -> NodeResult:
    o = call.db.get(Order, data.order_id)
    if o is None:
        return NodeResult(exit="fail", detail="没有这单")
    lock_row(call.db, o)  # 同一版连交几次（网络重试）：PG 上后到的等前一个提交、看到新状态再判断（SQLite 写会话本来就独占）
    s = versions.settings()
    try:
        facts = versions.check_package(call.db, call.ctx, o, s)
    except CheckFailed as e:
        record_event(call.db, "delivery.package_rejected", f"order:{o.id}", {**e.as_dict(), "by": call.by, "source": data.source})
        return NodeResult(exit="fail", detail=str(e))
    v = versions.record_version(call.db, o, facts, source=data.source, note=data.note, revision_id=data.revision_id)
    try:
        nxt = service.submit_package(call.db, call.ctx, o, by=call.by, note=data.note)  # 发 package_received：出图 → 发布
    except ValueError as e:
        return NodeResult(exit="fail", detail=str(e))
    return NodeResult(exit="ok", output=PackageOut(order_id=o.id, round=nxt, stage=o.stage, slide_count=facts.slide_count,
                                                   page_count=len(facts.pages), final_file_ids=[f.id for f in facts.finals],
                                                   version_id=v.id))


CARD = NodeCard(
    id="deliver.receive",
    name="收成品包",
    description="制作方做好一版后，把 pptx、讲稿和每页的整页图交上来：这里检查齐不齐（缺讲稿、缺页、页数和 pptx 对不上、"
                "整页图是缩略图、文件坏都不收，原因三件写回给制作方），把最终版锁在库里（客人这时拿不到），记一行版本表，"
                "发流程事件 package_received，接着出水印图。已完成之后交的直接放最终版。",
    category="交付",
    tech=["制作方接口 POST /api/intake/production/orders/{id}/package（令牌 PRODUCTION_TOKEN）", "scripts/production_cli.py deliver",
          "后台上传成品 + POST /api/admin/intake/orders/{id}/deliver", "zipfile 数 pptx 页数（不含隐藏页）", "Pillow 读整页图尺寸",
          "core.storage", "版本表 delivery_versions"],
    input_model=PackageIn,
    output_model=PackageOut,
    exits=[NodeExit(key="ok", label="收了，去出水印图（已完成之后的直接放最终版）", kind="ok"),
           NodeExit(key="fail", label="不收：缺讲稿、缺页、页数对不上、缩略图、文件坏、这一步不收", kind="fail")],
    config=["DELIVERY_REQUIRED_FINALS：必须交哪些最终版（默认 PPT、讲稿）", "DELIVERY_CHECK_SLIDE_COUNT：pptx 页数要和整页图张数对上",
            "WATERMARK_LONG_MIN：整页图长边下限 1600"],
    emits=["delivery.package_received", "delivery.package_rejected", "intake.stage"],
    listens=["无"],
    replaceable=["来源可换：制作方命令行（默认）、后台人工上传、以后接 API 的做单进程", "科研绘图定制单：DELIVERY_REQUIRED_FINALS 设空，整页图就是成品图"],
    failure="不合格整版不收，原因三件（错在哪、怎么改、看哪）返回给制作方；同一版重传覆盖版本行（按 订单+版次 幂等）。",
    owner="E",
    status="已有",
)
register(CARD, handler)
