"""按保留期清理运维数据（ops.retention_purge）。天数全部从设置读（OpsConfig.retention），这里不许写死（scripts/check.py 规矩 19）。

- 原始 ops_samples：删之前先把要删的那几小时聚合进 ops_hourly（store.rollup 已经跑过的就不重复）。
- events 表是平台申诉的凭据，运维不清理（保存期限待法务确认，见 docs/运维/数据保存期限.md）。
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.core.notify_policy import NotifyItem
from app.ops.config import OpsConfig
from app.ops.models import OpsAlert, OpsError, OpsHourly, OpsSample, OpsVisitor
from app.ops.store import rollup


def purge(db: Session, cfg: OpsConfig, *, now: datetime, tzname: str) -> dict[str, int]:
    r = cfg.retention
    out: dict[str, int] = {}
    raw_cut = now - timedelta(days=r.raw_days)
    # 要删的原始行所在的小时必须已经聚合过：没聚合（比如定时停过）先聚合
    oldest_hourly = db.scalar(select(func.max(OpsHourly.hour)))
    if oldest_hourly is None or oldest_hourly < raw_cut.replace(minute=0, second=0, microsecond=0):
        rollup(db, now=now)
    out["ops_samples"] = db.execute(delete(OpsSample).where(OpsSample.minute < raw_cut)).rowcount or 0
    out["ops_hourly"] = db.execute(delete(OpsHourly).where(OpsHourly.hour < now - timedelta(days=r.hourly_days))).rowcount or 0
    out["ops_errors"] = db.execute(delete(OpsError).where(OpsError.at < now - timedelta(days=r.errors_days))).rowcount or 0
    from zoneinfo import ZoneInfo

    day_cut = (now.astimezone(ZoneInfo(tzname)) - timedelta(days=r.visitors_days)).strftime("%Y-%m-%d")
    out["ops_visitors"] = db.execute(delete(OpsVisitor).where(OpsVisitor.day < day_cut)).rowcount or 0
    out["ops_alerts"] = db.execute(delete(OpsAlert).where(OpsAlert.status == "resolved",
                                                          OpsAlert.last_at < now - timedelta(days=r.alerts_days))).rowcount or 0
    out["core_notify_items"] = db.execute(delete(NotifyItem).where(NotifyItem.at < now - timedelta(days=r.notify_days))).rowcount or 0
    db.flush()
    return out
