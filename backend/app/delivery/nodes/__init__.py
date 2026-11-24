"""制作与交付（模块 E）的节点。每个文件一个节点：说明卡 CARD + handler，文件末尾 register。

导入这个包就把本包所有节点登记进注册表（app/core/nodes.py）。节点文件之间不许互相 import（scripts/check.py 第 14 条），
要用别的节点走 run_node。节点背后的实现在 delivery/versions.py、watermark.py、checks.py、outbound.py、sla.py。
7 个节点：deliver.receive、deliver.watermark、deliver.preview、revision.collect、confirm.receipt、gate.final、deliver.sla
（第一期由订单中枢包壳，11-18 模块 E 接手；说明卡格式见 docs/任务单/06_订单中枢契约.md 第四节）。
"""

from __future__ import annotations

import importlib
import pkgutil

for _m in pkgutil.iter_modules(__path__):
    importlib.import_module(f"{__name__}.{_m.name}")
