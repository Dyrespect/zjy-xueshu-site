"""入口模块（D）的节点：entry.route / entry.notice / entry.webchat / entry.wecom / entry.redeem_page / customer.memory /
notify.email。每个文件一个节点：说明卡 CARD + handler，文件末尾 register；入口节点还登记一份 EntrySpec（app/channels/entries.py）。

导入这个包就把本包所有节点登记进注册表（app/core/nodes.py）。节点文件之间不许互相 import（scripts/check.py 拦），
要用别的节点走 run_node。背后的实现在 channels/inbound.py（分流）、texts.py（话术）、memory.py（客户与记忆）、
redeem.py（兑换页）、wecom.py（微信客服收）、dispatch.py（发件员）、mailer.py（发信）。
"""

from __future__ import annotations

import importlib
import pkgutil

for _m in pkgutil.iter_modules(__path__):
    importlib.import_module(f"{__name__}.{_m.name}")
