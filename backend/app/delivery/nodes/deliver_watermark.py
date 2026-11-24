"""deliver.watermark 水印出图。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.delivery import versions
from app.delivery.checks import CheckFailed
from app.delivery.watermark import WatermarkError
from app.intake.models import Order


class WatermarkIn(BaseModel):
    order_id: int
    via: Literal["flow", "call"] = Field(default="call", description="flow：引擎进「出水印图」时调；call：后台点「重出图」")
    mode: Literal["auto", "sync", "queue"] = Field(default="auto", description="auto：页数少当场出、多了进队列")


class WatermarkOut(BaseModel):
    order_id: int = 0
    round: int
    proof_file_ids: list[int] = Field(default_factory=list)
    impl: str = "tile_image"
    queued: bool = False
    version_id: int | None = None
    spec: dict = Field(default_factory=dict)


def handler(call: NodeCall, data: WatermarkIn) -> NodeResult:
    o = call.db.get(Order, data.order_id)
    if o is None:
        return NodeResult(exit="fail", detail="没有这单")
    s = versions.settings()
    v = versions.ensure_version(call.db, o)
    if not v.page_file_ids:
        return NodeResult(exit="fail", detail="这一版没有整页图")
    sync = data.mode == "sync" or (data.mode == "auto" and v.page_count <= s.DELIVERY_SYNC_MAX_PAGES)
    if not sync:
        versions.queue(v)
        return NodeResult(exit="wait", output=WatermarkOut(order_id=o.id, round=v.round, queued=True, version_id=v.id),
                          detail=f"{v.page_count} 页进了出图队列，出完自动发布")
    try:
        done = versions.render_now(call.db, call.ctx, v, s, by=call.by)
    except (WatermarkError, CheckFailed, OSError) as e:
        call.ctx.notifier.send(f"#{o.id} 第 {v.round} 版出水印图出错（{v.attempts} 次）：{str(e)[:120]}", link="/admin/orders", level="urgent", kind="出图失败", who=f"order:{o.id}")
        return NodeResult(exit="fail", detail=str(e))
    if done is None:
        return NodeResult(exit="fail", detail="这一版出图期间被重传了，按新的一版重出")
    return NodeResult(exit="ok", output=WatermarkOut(order_id=o.id, round=done.round, proof_file_ids=list(done.proof_file_ids),
                                                     version_id=done.id, spec=done.watermark_spec))


CARD = NodeCard(
    id="deliver.watermark",
    name="水印出图",
    description="把这一版每页的整页图铺上斜纹水印（写完整单号，每页位置和轻微扭曲都不同），底栏写第几版、第几页，"
                "存成长边 1920 的 JPEG：看得清、不能直接拿去用，没有任何文字层和元数据。页数少当场出，多了进后台队列，"
                "出完发 proof_ready 接着发布。",
    category="交付",
    tech=["Pillow（app/delivery/watermark.py，纯函数）", "中文字体（服务器镜像装 fonts-wqy-microhei）",
          "后台圈 app/delivery/tick.py（asyncio + 线程里出图，不占数据库写锁）", "版本表 delivery_versions",
          "checks.verify_proof（只许 JPEG 整页图）"],
    input_model=WatermarkIn,
    output_model=WatermarkOut,
    exits=[NodeExit(key="ok", label="当场出完了", kind="ok"),
           NodeExit(key="wait", label="进了出图队列，出完发 proof_ready", kind="wait"),
           NodeExit(key="fail", label="出图出错（整页图坏了、太小），后台圈会重试", kind="fail")],
    config=["config.delivery.watermark_alpha：水印浓淡（后台设置，先用 0.20，Edison 看样张定）",
            "DELIVERY_SYNC_MAX_PAGES：几页以内当场出（默认 4）", "WATERMARK_LONG_SIDE 1920、WATERMARK_LONG_MIN 1600、"
            "WATERMARK_QUALITY 82、WATERMARK_WARP（每页扭曲）", "DELIVERY_RENDER_RETRY_SECONDS、DELIVERY_RENDER_MAX_ATTEMPTS：失败重试"],
    emits=["delivery.watermarked", "node.failed"],
    listens=["无"],
    replaceable=["tile_image（默认：每页一张 JPEG）", "pdf_image（同样的图拼成只有图片的 PDF）", "maker_side（制作方在 Mac 上用同一个函数出好，服务器只验）"],
    failure="失败记版本表 error 和 node.failed，后台圈隔 1 分钟重试，3 次不成通知负责人、后台点「重出图」；"
            "同一版重传按版本行的更新时间作废旧图（按 订单+版次 幂等），交付页只认版本表记的那几张。",
    owner="E",
    status="已有",
)
register(CARD, handler)
