"""运维的节点（docs/任务单/07_运维与数据_设计.md 第十一节）。导入本包 = 把它们登记进注册表（app/core/nodes.py）。"""

from app.ops.nodes import (  # noqa: F401
    ops_alert_eval,
    ops_backup_prune,
    ops_backup_run,
    ops_daily_report,
    ops_health_check,
    ops_lifecycle_scan,
    ops_metrics_flush,
    ops_metrics_rollup,
    ops_restore_drill,
    ops_retention_purge,
    ops_send,
)
