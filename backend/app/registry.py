"""业务模块清单（拼装用，跟 main.py 同一层；core 不许 import 这里）。

加一个业务模块 = 在 BUSINESS_MODULES 里加名字 + 建 app/<名字>/router.py（节点放 app/<名字>/nodes/）。
（这一步属于改底座，先跟总负责人说。11-18 按主窗口转来的模块 B、C 设计加了 shop（自有渠道）、platforms（平台适配器），等主窗口确认；
同日开票模块加了 invoices（docs/任务单/07_开票_设计.md），等主窗口确认；
科研绘图聚人加了 gather（docs/任务单/07_科研绘图聚人_设计.md），等主窗口确认；
同日站点整合加了 website（官网设置、robots、下单前同意留痕，docs/任务单/08_官网整合_说明.md），等主窗口确认；
运维加了 ops（docs/任务单/07_运维与数据_设计.md），等主窗口确认。）
"""

from __future__ import annotations

import importlib
from types import ModuleType

BUSINESS_MODULES: tuple[str, ...] = ("figures", "intake", "channels", "delivery", "handoffs", "shop", "platforms", "invoices", "gather", "website", "ops", "admin")

# core 自己的表所在的模块；core 新增表时在这里加一行
CORE_MODEL_MODULES: tuple[str, ...] = ("app.core.events", "app.core.tasks", "app.core.ratelimit", "app.core.notify_policy")


def _import_optional(module_name: str) -> ModuleType | None:
    try:
        return importlib.import_module(module_name)
    except ModuleNotFoundError as e:
        if e.name == module_name or module_name.startswith(f"{e.name}."):  # 只有「这个文件 / 这个包本来就没有」才忽略；内部 import 错了照样报
            return None
        raise


def import_all_models() -> None:
    """把所有表定义加载进 Base.metadata（Alembic 和测试用）。表放 app/<模块>/models.py。"""
    for name in CORE_MODEL_MODULES:
        importlib.import_module(name)
    for name in BUSINESS_MODULES:
        _import_optional(f"app.{name}.models")


def import_all_nodes() -> None:
    """把每个业务模块的 nodes/ 导入一遍，节点登记进注册表 app/core/nodes.py（顶层设计第十八节）。
    各模块的 router.py 也会导入自己的 nodes（启动时就登记了）；这里给脚本、测试、节点目录页用。"""
    for name in BUSINESS_MODULES:
        _import_optional(f"app.{name}.nodes")


def router_modules() -> dict[str, ModuleType]:
    """有 router.py 的业务模块（shop、platforms 这些新模块还在设计时没有 router.py，先跳过）。"""
    out = {}
    for name in BUSINESS_MODULES:
        mod = _import_optional(f"app.{name}.router")
        if mod is not None:
            out[name] = mod
    return out
