"""接口里常用的依赖，一处 import：

    from app.core.deps import get_db, get_settings_dep, get_storage, get_notifier, require_admin, client_ip
    from app.core.deps import get_write_db, get_ratelimiter, get_scheduler   # 底座可扩展（11-18）

    @router.post("/x")
    def x(db: Session = Depends(get_db), storage: Storage = Depends(get_storage)): ...

这些东西都在 create_app 里建好放在 app.state 上；测试里换成假实现也只换 app.state。
"""

from __future__ import annotations

from fastapi import Request

from app.core.auth import require_admin
from app.core.config import Settings
from app.core.db import Database, get_db, get_write_db
from app.core.notify import Notifier
from app.core.net import client_ip
from app.core.ratelimit import RateLimits
from app.core.storage import Storage
from app.core.tasks import Scheduler


def get_settings_dep(request: Request) -> Settings:
    return request.app.state.settings


def get_database(request: Request) -> Database:
    """拿整个库对象（要在请求之外开会话时用，比如交给后台任务）。"""
    return request.app.state.db


def get_storage(request: Request) -> Storage:
    return request.app.state.storage


def get_notifier(request: Request) -> Notifier:
    return request.app.state.notifier


def get_ratelimiter(request: Request) -> RateLimits:
    """限流（计数在库里或 Redis，不在进程内存）。接口一开始、动库之前调。"""
    return request.app.state.ratelimit


def get_scheduler(request: Request) -> Scheduler:
    return request.app.state.scheduler


__all__ = [
    "get_db",
    "get_write_db",
    "get_ratelimiter",
    "get_scheduler",
    "get_database",
    "get_settings_dep",
    "get_storage",
    "get_notifier",
    "require_admin",
    "client_ip",
]
