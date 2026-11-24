"""admin 模块的接口入口。main.py 已经把它挂在 `/api/admin` 下，不用再改 main.py。

- 整个后台 router 默认要求登录（require_admin）；不要在这里开不登录的口子。
- 子接口按文件拆：在 app/admin/ 下建 `xxx_router.py`，导出 `router = APIRouter(prefix="/xxx")`，
  这里会自动挂上，并且自动继承登录要求。图库那边的后台接口（figures_router.py）就靠这个挂，
  别的 agent 不用改本文件。**改本文件时保留最下面自动挂子 router 的几行。**
- 需要启动 / 关闭时做事，在本文件定义 `lifespan(app)`（asynccontextmanager），main.py 会自动调用。
"""

import importlib
import pkgutil
from pathlib import Path

from fastapi import APIRouter, Depends

from app.core.auth import require_admin

router = APIRouter(dependencies=[Depends(require_admin)])


def include_sub_routers(parent: APIRouter, package_dir: Path, package_name: str) -> list[str]:
    """把 package_dir 下所有 `*_router.py` 的 `router` 挂到 parent 上，返回挂了哪些。"""
    mounted = []
    for info in sorted(pkgutil.iter_modules([str(package_dir)]), key=lambda i: i.name):
        if info.name.endswith("_router"):
            mod = importlib.import_module(f"{package_name}.{info.name}")
            parent.include_router(mod.router)
            mounted.append(info.name)
    return mounted


include_sub_routers(router, Path(__file__).parent, __package__ or "app.admin")
