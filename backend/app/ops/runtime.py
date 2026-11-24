"""运维的运行环境：节点拿到的 call.ctx 就是这个（app、各种配置、计数器、发送层、测试时换掉的传输层）。

测试里在进 lifespan 之前设：app.state.ops_settings（OpsSettings(_env_file=None, ...)）、app.state.ops_transport（httpx.MockTransport，
飞书和外部依赖检查都走它，不连外网）、app.state.ops_cert_probe（假的证书读数函数）、app.state.ops_disk_probe（假的磁盘读数）。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

from app.core.config import Settings
from app.core.db import Database
from app.core.notify import Notifier
from app.ops.collector import Collector
from app.ops.settings import OpsSettings


@dataclass
class OpsCtx:
    app: Any
    settings: Settings
    osettings: OpsSettings
    database: Database
    notifier: Notifier
    collector: Collector
    transport: httpx.BaseTransport | None = None
    cert_probe: Callable[[str, float], int] | None = None  # (域名, 超时) -> 剩余天数；测试换
    disk_probe: Callable[[Path], Any] | None = None  # 路径 -> shutil.disk_usage 那样的 (total, used, free)；测试换
    now_fn: Callable[[], datetime] = field(default=lambda: datetime.now(timezone.utc))
    cache: dict[str, Any] = field(default_factory=dict)

    def now(self) -> datetime:
        return self.now_fn()

    @property
    def backup_dir(self) -> Path:
        return self.osettings.OPS_BACKUP_DIR or (self.settings.DATA_DIR / "backups")

    def admin_url(self, link: str) -> str:
        """后台页面的完整网址（飞书消息里点得开）。"""
        base = self.settings.PUBLIC_BASE_URL.rstrip("/")
        return f"{base}{link if link.startswith('/') else '/' + link}"


def get_ops(app: Any) -> OpsCtx:
    ctx = getattr(app.state, "ops", None)
    if ctx is None:
        os_: OpsSettings = getattr(app.state, "ops_settings", None) or OpsSettings()
        settings: Settings = app.state.settings
        collector = Collector(settings.SESSION_SECRET.get_secret_value() or "ops-dev", os_.OPS_TIMEZONE)
        collector.enabled = os_.OPS_METRICS_ENABLED
        ctx = OpsCtx(app=app, settings=settings, osettings=os_, database=app.state.db, notifier=app.state.notifier,
                     collector=collector, transport=getattr(app.state, "ops_transport", None),
                     cert_probe=getattr(app.state, "ops_cert_probe", None), disk_probe=getattr(app.state, "ops_disk_probe", None))
        app.state.ops = ctx
    return ctx
