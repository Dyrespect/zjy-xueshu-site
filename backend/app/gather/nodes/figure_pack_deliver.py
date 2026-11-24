"""figure.pack_deliver 发网盘链接：流程一进「发链接」就跑；后台没贴链接就停在「等链接」并通知负责人，贴好自动补发。"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select

from app.core.events import Event, record_event
from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.gather import service
from app.gather.models import FigureUnlock, PackGrant
from app.gather.models_io import DeliverIn, DeliverOut


def handler(call: NodeCall, data: DeliverIn) -> NodeResult:
    db = call.db
    unlock = db.get(FigureUnlock, data.subject_id)
    if unlock is None:
        return NodeResult(exit="no_pack", detail="没有这次领取")
    pack = service.active_pack(db, unlock.tier)
    if pack is None:
        since = service.now() - timedelta(hours=6)
        told = db.scalar(select(Event.id).where(Event.type == "figure.pack_missing", Event.created_at >= since).limit(1))
        record_event(db, "figure.pack_missing", f"figure_unlock:{unlock.id}", {"tier": unlock.tier})
        if told is None and call.ctx.notifier is not None:
            call.ctx.notifier.send("【图库】有人核验过了，但后台还没贴全量包的网盘链接：后台「聚人」→「网盘链接」贴上，贴好自动补发。", link="/admin/gather", level="digest", kind="图库网盘链接")
        return NodeResult(exit="no_pack", output=DeliverOut(tier=unlock.tier), detail="后台还没贴这一档的网盘链接")
    grant = db.scalar(select(PackGrant).where(PackGrant.unlock_id == unlock.id, PackGrant.tier == unlock.tier))
    if grant is None:
        grant = PackGrant(unlock_id=unlock.id, pack_id=pack.id, tier=unlock.tier, door=unlock.door,
                          channel_user=unlock.channel_user, sent_at=service.now())
        db.add(grant)
        exit_key = "sent"
    else:
        grant.pack_id = pack.id
        grant.resend_count += 1
        grant.sent_at = service.now()
        exit_key = "resent"
    unlock.sent_at = service.now()
    db.flush()
    record_event(db, "figure.pack_sent", f"figure_unlock:{unlock.id}",  # 发链接留痕：谁、哪一版、第几次
                 {"pack_id": pack.id, "version": pack.version, "tier": pack.tier, "resend": grant.resend_count,
                  "channel_user": unlock.channel_user[:16], "door": unlock.door})
    return NodeResult(exit=exit_key, output=DeliverOut(pack_version=pack.version, tier=pack.tier, grant_id=grant.id))


CARD = NodeCard(
    id="figure.pack_deliver",
    name="发网盘链接",
    description="把当前上线的全量包（或小包）链接和提取码发给这个人，记下谁在什么时候拿了哪一版（留痕）；他说打不开就重发最新的。"
                "图库更新不再私发，靠公众号通知。后台没贴链接就停着等，贴好自动补发。",
    category="交付",
    tech=["表 figure_packs（后台「网盘链接」贴，代码里不写死）、figure_pack_grants（发链接留痕）",
          "网页这扇门：链接只在流程到「已发链接」后由 GET /api/gather/unlock/{码} 返回", "飞书通知（没贴链接时）"],
    input_model=DeliverIn,
    output_model=DeliverOut,
    exits=[
        NodeExit(key="sent", label="发了", kind="ok"),
        NodeExit(key="resent", label="重发最新版", kind="ok"),
        NodeExit(key="no_pack", label="后台还没贴这一档的链接", kind="wait"),
    ],
    config=["pack_text：发出那段话的模板（不许写死链接，链接只在库里）", "网盘：百度（默认，Edison 定的）/ 夸克 / 阿里云盘"],
    emits=["figure.pack_sent", "figure.pack_missing（通知负责人去贴链接；6 小时内只通知一次）"],
    listens=["无（新版上线由 figure.release 在等链接的领取上发流程事件 pack_released）"],
    replaceable=["百度网盘（默认）", "夸克网盘", "阿里云盘", "COS 签名链接（要钱，不默认）"],
    failure="同一次领取同一档只记一条发放，重发只加次数（幂等）；没链接 → 停在「等链接」 + 通知，贴好后自动补发。",
    owner="L",
    status="要新做",
)
register(CARD, handler)
