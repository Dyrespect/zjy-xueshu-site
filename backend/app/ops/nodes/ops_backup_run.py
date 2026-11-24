"""ops.backup_run 备份。"""

from __future__ import annotations

from app.core.events import record_event
from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.core.redact import redact_text
from app.ops import backup
from app.ops.config import load_config
from app.ops.models_io import BackupOut, Empty


def handler(call: NodeCall, data: Empty) -> NodeResult:
    ctx = call.ctx
    try:
        out = backup.run_backup(ctx, load_config(call.db), now=data.now or ctx.now())
    except Exception as e:  # noqa: BLE001  失败记事件，告警规则 backup_failed 会报
        why = redact_text(f"{type(e).__name__}: {e}")[:300]
        record_event(call.db, "ops.backup_failed", "ops:backup", {"error": why, "engine": backup.engine(ctx), "by": call.by})
        return NodeResult(exit="fail", output=BackupOut(error=why), detail=why)
    record_event(call.db, "ops.backup_done", "ops:backup", {
        "name": out.name, "engine": out.engine, "where": out.path, "db_bytes": out.db_bytes, "files_count": out.files_count,
        "files_bytes": out.files_bytes, "seconds": out.seconds, "verify": out.verify, "weekly": out.weekly, "note": out.note,
        "by": call.by})
    return NodeResult(exit="ok", output=out)


CARD = NodeCard(
    id="ops.backup_run",
    name="备份",
    description="每天 03:30（设置里改）备份一次：先用 SQLite 自带的在线备份把数据库拷一份（不是直接拷文件，网站照常用），查完整性、"
                "数订单数和实付合计写进清单；再交给 restic 连同客户文件一起备份（加密、去重，本机仓库或腾讯云对象存储）。"
                "restic 还没装的时候用内置兜底：只备份数据库、只在本机。",
    category="运营",
    tech=["sqlite3 在线备份（app/core/dbbackup.py）", "restic（BSD-2，单个程序；要 Edison 点头装）", "gzip（内置兜底）",
          "腾讯云 COS（restic 的 s3 仓库，默认关）"],
    input_model=Empty,
    output_model=BackupOut,
    exits=[NodeExit(key="ok", label="备好了", kind="ok"), NodeExit(key="fail", label="失败了（告警会报）", kind="fail")],
    config=["backup.enabled、backup.time、backup.verify（核对哪些数）", "OPS_BACKUP_ENGINE、OPS_BACKUP_DIR、OPS_BACKUP_INCLUDE、"
            "OPS_RESTIC_BIN、OPS_RESTIC_REPOSITORY、OPS_RESTIC_PASSWORD_FILE、OPS_BACKUP_COS_ENABLED（默认关）、OPS_BACKUP_COS_CREDENTIALS_FILE（.env）"],
    emits=["ops.backup_done", "ops.backup_failed"],
    listens=["无"],
    replaceable=["restic（默认，装了就用）", "内置兜底（只有数据库）", "Litestream（数据库连续备份，单独一个进程，配置样例 deploy/ops/litestream.yml）",
                 "PostgreSQL 以后：托管库自带自动备份 / pgBackRest / WAL-G"],
    failure="失败记 ops.backup_failed（错误已脱敏），告警规则 backup_failed 立刻推；同一天调度只跑一次，后台可以点「现在备份」重来。"
            "restic 自己保证一次备份要么完整、要么不算数。",
    owner="运维",
    status="要新做",
)
register(CARD, handler)
