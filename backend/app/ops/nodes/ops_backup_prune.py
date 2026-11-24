"""ops.backup_prune 备份保留。"""

from __future__ import annotations

from app.core.events import record_event
from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.ops import backup
from app.ops.config import load_config
from app.ops.models_io import Empty, PruneOut


def handler(call: NodeCall, data: Empty) -> NodeResult:
    out = backup.prune(call.ctx, load_config(call.db))
    record_event(call.db, "ops.backup_pruned", "ops:backup", {"kept": len(out.kept), "removed": out.removed[:50], "by": call.by})
    return NodeResult(exit="ok", output=out)


CARD = NodeCard(
    id="ops.backup_prune",
    name="备份保留",
    description="备份做完接着跑：留最近 7 天每天一份、最近 4 周每周一份（数字在设置里），更早的删掉。用 restic 时就是 "
                "restic forget --keep-daily 7 --keep-weekly 4 --prune；内置兜底按同样的规则删本机文件。",
    category="运营",
    tech=["restic forget --prune", "内置兜底：删 OPS_BACKUP_DIR/builtin 下过期的文件"],
    input_model=Empty,
    output_model=PruneOut,
    exits=[NodeExit(key="ok", label="删好了", kind="ok"), NodeExit(key="fail", label="出错（明天再来）", kind="fail")],
    config=["backup.keep_daily（7）、backup.keep_weekly（4）、backup.weekly_weekday（周日）"],
    emits=["ops.backup_pruned"],
    listens=["无"],
    replaceable=["对象存储的生命周期规则（只用 COS 时）"],
    failure="只删按规则不该留的；出错不删任何东西，明天再来。最新一份永远留着。",
    owner="运维",
    status="要新做",
)
register(CARD, handler)
