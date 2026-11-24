"""拼装：建 app、挂底座、挂各业务模块的 router、生产时挂前端。

启动：在 backend/ 下 `uvicorn app.main:app --port 8710 --reload`（scripts/dev.sh 已经写好）。
测试：`create_app(Settings(...), notifier=FakeNotifier())`，不要 import 模块级的 `app`。

业务模块不用改这个文件：
- 接口：写在 app/<模块>/router.py 的 `router` 上，自动挂在 /api/<模块> 下。
- 启动 / 关闭时要做的事：在 app/<模块>/router.py 定义 `lifespan(app)`，这里自动调用。
- 站点根上的路径（/robots.txt 这类）：同文件导出 `root_router`，不加 /api 前缀，挂在前端兜底路由前面。
- 要用底座：`from app.core.deps import get_db, get_storage, get_notifier, ...`（不要 import 本文件）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from pathlib import Path

import asyncio
import contextlib
import logging

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from app.core import access
from app.core.auth import AuthManager, require_admin
from app.core.auth import router as auth_router
from app.core.config import Settings, get_settings
from app.core.db import Database, PoolSettings
from app.core.headers import SecurityHeadersMiddleware
from app.core.log import setup_logging
from app.core.notify import Notifier, build_notifier
from app.core.ratelimit import build_ratelimiter
from app.core.reqlog import RequestContextMiddleware
from app.core.storage import Storage, build_storage
from app.core.tasks import build_scheduler, metrics
from app.registry import router_modules

health_router = APIRouter()


@health_router.get("/health", dependencies=[Depends(access.public)])
def health(request: Request) -> JSONResponse:
    try:
        with request.app.state.db.engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "error"
    body = {"status": "ok" if db_status == "ok" else "error", "db": db_status}
    return JSONResponse(body, status_code=200 if db_status == "ok" else 503)


@health_router.get("/health/tasks", dependencies=[Depends(require_admin)])
def task_metrics(request: Request) -> JSONResponse:
    """后台任务的指标：队列长度、最老一条等了多久、死信、定时任务上次耗时和出错（运维采；要后台登录）。"""
    return JSONResponse(metrics(request.app.state.db))


def _mount_frontend(app: FastAPI, dist: Path) -> None:
    """生产时：frontend/dist 当静态文件挂在 /，前端路由回落到 index.html（/api/* 除外）。"""
    index = dist / "index.html"
    if not index.is_file():
        return
    dist = dist.resolve()
    if (dist / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(404, detail="Not Found")
        if full_path:
            candidate = (dist / full_path).resolve()
            if dist in candidate.parents and candidate.is_file():
                return FileResponse(candidate)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})


def create_app(
    settings: Settings | None = None,
    *,
    notifier: Notifier | None = None,
    storage: Storage | None = None,
    role: str = "web",
) -> FastAPI:
    """role：web（网站进程；BACKGROUND_IN_WEB=true 时顺带跑后台任务）| worker（app/worker.py 用，调度器由它自己跑）。"""
    settings = settings or get_settings()
    setup_logging(settings.LOG_LEVEL, settings.LOG_FORMAT, settings.LOG_FILE)
    settings.DATA_DIR.mkdir(parents=True, exist_ok=True)
    modules = router_modules()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with AsyncExitStack() as stack:
            for mod in modules.values():
                hook = getattr(mod, "lifespan", None)
                if hook is not None:
                    await stack.enter_async_context(hook(app))  # 各模块在这里向 app.state.scheduler 登记定时任务
            sched_task = None
            if role == "web" and settings.BACKGROUND_IN_WEB:
                sched_task = asyncio.create_task(app.state.scheduler.run_forever())
            elif role == "web":
                logging.getLogger("app.main").info("后台任务不在网站进程里跑（BACKGROUND_IN_WEB=false）：要有 python -m app.worker 在跑")
            try:
                yield
            finally:
                if sched_task is not None:
                    app.state.scheduler.stop()
                    try:
                        await asyncio.wait_for(sched_task, timeout=settings.WORKER_GRACE_SEC)
                    except (asyncio.TimeoutError, asyncio.CancelledError):
                        sched_task.cancel()
                        with contextlib.suppress(asyncio.CancelledError, Exception):
                            await sched_task
        app.state.db.dispose()
        app.state.ratelimit.close()

    app = FastAPI(
        title="学术汇报平台",
        lifespan=lifespan,
        docs_url="/api/docs" if settings.APP_ENV == "dev" else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if settings.APP_ENV == "dev" else None,  # 生产不公开接口清单
    )
    app.add_middleware(SecurityHeadersMiddleware)  # 不缓存、noindex 这些响应头（app/core/headers.py）
    app.add_middleware(RequestContextMiddleware)  # 请求号、访问日志、运维计数（app/core/reqlog.py；放最外层，计时包住全部）
    app.state.settings = settings
    app.state.role = role
    app.state.db = Database(settings.DATABASE_URL, PoolSettings.from_settings(settings))
    app.state.storage = storage or build_storage(settings)
    app.state.notifier = notifier or build_notifier(settings, app.state.db)  # 外面包着通知策略（app/core/notify_policy.py）
    app.state.ratelimit = build_ratelimiter(settings, app.state.db)
    app.state.scheduler = build_scheduler(app.state.db, settings, app, role)
    app.state.auth = AuthManager(settings, app.state.ratelimit)

    app.include_router(health_router, prefix="/api", tags=["health"])
    app.include_router(health_router, tags=["health"], include_in_schema=False)  # /health：给 nginx、外部拨测用的浅检查
    app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
    for name, mod in modules.items():
        app.include_router(mod.router, prefix=f"/api/{name}", tags=[name])
        root = getattr(mod, "root_router", None)  # 站点根上的文件（官网的 /robots.txt、/sitemap.xml），不加前缀
        if root is not None:
            app.include_router(root, tags=[name])

    _mount_frontend(app, settings.FRONTEND_DIST)  # 必须最后挂：兜底路由不能挡住 /api
    return app


_app: FastAPI | None = None


def __getattr__(name: str) -> FastAPI:
    """`uvicorn app.main:app` 取 `app` 时才建（PEP 562），import 本文件本身没有副作用。"""
    global _app
    if name == "app":
        if _app is None:
            _app = create_app()
        return _app
    raise AttributeError(name)
