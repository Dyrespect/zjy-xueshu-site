"""自有渠道和支付的节点。每个文件一个节点：说明卡 CARD + handler，文件末尾 register。

导入这个包就把本包所有节点登记进注册表（app/core/nodes.py）。节点文件之间不许互相 import（scripts/check.py 拦），
要用别的节点走 run_node。背后的实现在 shop/service.py（下单、回调、退款）、gateways/（调网关）、paycore/（签名、验签、二维码）。
"""

from __future__ import annotations

import importlib
import pkgutil

for _m in pkgutil.iter_modules(__path__):
    importlib.import_module(f"{__name__}.{_m.name}")
