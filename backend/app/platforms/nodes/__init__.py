"""平台渠道的节点。每个文件一个节点：说明卡 CARD + handler，文件末尾 register。

导入这个包就把本包所有节点登记进注册表。节点文件之间不许互相 import，要用别的节点走 run_node。
背后的实现在 platforms/service.py（录单、核对、信号）、adapters.py（各渠道的适配器）、redline.py（红线词表）。
"""

from __future__ import annotations

import importlib
import pkgutil

for _m in pkgutil.iter_modules(__path__):
    importlib.import_module(f"{__name__}.{_m.name}")
