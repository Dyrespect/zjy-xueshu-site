"""figure.release 图库发版：Mac 上打好包、传网盘，后台贴链接这一版就上线；卡在「等链接」的人自动补发。"""

from __future__ import annotations

from sqlalchemy import select

from app.core.events import record_event
from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.gather import service
from app.gather.models import FigurePack
from app.gather.models_io import ReleaseIn, ReleaseOut


def handler(call: NodeCall, data: ReleaseIn) -> NodeResult:
    db = call.db
    if not data.url.startswith("https://"):
        return NodeResult(exit="bad", detail="网盘链接要以 https:// 开头（从网盘「分享」里复制完整链接）")
    pack = db.scalar(select(FigurePack).where(FigurePack.version == data.version, FigurePack.tier == data.tier))
    if pack is None:
        pack = FigurePack(version=data.version, tier=data.tier)
        db.add(pack)
    pack.url, pack.extract_code, pack.provider = data.url.strip(), data.extract_code.strip(), data.provider
    pack.count, pack.size_mb, pack.manifest_sha256, pack.note = data.count, data.size_mb, data.manifest_sha256, data.note
    pack.active = True
    pack.updated_at = service.now()
    db.flush()
    for other in db.scalars(select(FigurePack).where(FigurePack.tier == data.tier, FigurePack.id != pack.id,
                                                    FigurePack.active.is_(True))):
        other.active = False
    record_event(db, "figure.library_released", f"figure_pack:{pack.id}",
                 {"version": pack.version, "tier": pack.tier, "count": pack.count})
    resent = 0
    for u in service.waiting_for_pack(db, data.tier):
        if service.emit(db, call.ctx, u, "pack_released", by=call.by, why=f"{pack.version} 版链接贴好了"):
            resent += 1
    return NodeResult(exit="released", output=ReleaseOut(pack_id=pack.id, active=True, resent=resent))


CARD = NodeCard(
    id="figure.release",
    name="图库发版",
    description="把图库（图、标签、出处、贡献者、使用说明）打成带版本号的全量包和小包（每个图型 10 张）；负责人传到网盘、在后台贴链接，这一版就上线，"
                "卡在「等链接」的人自动补发。网站、插件都显示同一个版本号。",
    category="运营",
    tech=["Mac 上的脚本 scripts/figures_build_pack.py（标准库，读内部索引和原图，跳过下架的图）", "上传网盘：负责人手动（不调网盘接口）",
          "后台 POST /api/admin/gather/packs（这个节点只做「登记新版本」）"],
    input_model=ReleaseIn,
    output_model=ReleaseOut,
    exits=[
        NodeExit(key="released", label="上线", kind="ok"),
        NodeExit(key="bad", label="链接不对", kind="fail"),
    ],
    config=["小包每个图型几张：脚本参数 --per-type（10）"],
    emits=["figure.library_released（version、tier、count）"],
    listens=["无"],
    replaceable=["网盘（百度 / 夸克 / 阿里）", "打包格式（文件夹 / 分卷 zip）"],
    failure="同一版本同一档再贴 = 改链接（不新建）；同一档只有一条在用；打包脚本按清单核 sha256，原图缺的跳过并列出来。",
    owner="L",
    status="要新做",
)
register(CARD, handler)
