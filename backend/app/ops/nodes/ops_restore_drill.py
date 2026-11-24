"""ops.restore_drill 恢复演练。"""

from __future__ import annotations

from app.core.events import record_event
from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.core.redact import redact_text
from app.ops import backup
from app.ops.config import load_config
from app.ops.models_io import DrillOut, Empty


def handler(call: NodeCall, data: Empty) -> NodeResult:
    try:
        out = backup.drill(call.ctx, load_config(call.db))
    except Exception as e:  # noqa: BLE001
        out = DrillOut(error=redact_text(f"{type(e).__name__}: {e}")[:300])
    ok = out.files_ok and not out.error
    record_event(call.db, "ops.restore_drilled", "ops:backup", {
        "ok": ok, "backup": out.backup, "integrity": out.integrity, "checks": out.checks, "error": out.error, "seconds": out.seconds,
        "by": call.by})
    return NodeResult(exit="ok" if ok else "fail", output=out, detail=out.error)


CARD = NodeCard(
    id="ops.restore_drill",
    name="恢复演练",
    description="每 30 天（设置里改）在临时目录里真恢复一次最新的备份：查数据库完整性，订单数、实付合计、自有网页实收、发票申请数、文件登记数、"
                "事件数要和备份时清单上的一样，迁移版本表在。做完删掉临时目录。后台也能点「现在演练」。",
    category="运营",
    tech=["restic restore（装了 restic）/ gzip 解压（内置兜底）", "sqlite3 integrity_check", "SQLAlchemy 数核对数（app/core/dbbackup.py）"],
    input_model=Empty,
    output_model=DrillOut,
    exits=[NodeExit(key="ok", label="恢复出来都对得上", kind="ok"), NodeExit(key="fail", label="恢复不了或对不上", kind="fail")],
    config=["backup.drill_every_days（30）、backup.verify（核对哪些数）"],
    emits=["ops.restore_drilled"],
    listens=["无"],
    replaceable=["litestream restore（装了 Litestream 后再加一项：恢复到某一时刻）"],
    failure="只在临时目录里做，不碰线上库；失败记事件、运维页显示红字。",
    owner="运维",
    status="要新做",
)
register(CARD, handler)
