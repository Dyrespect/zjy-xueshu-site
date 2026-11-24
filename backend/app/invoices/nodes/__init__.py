"""开票的节点（设计 docs/任务单/07_开票_设计.md 第五节）。导入本包 = 把它们登记进注册表（app/core/nodes.py）。

先导入 service：它把发票申请登记成能走流程的对象、把 flows/ 交给引擎。
"""

from app.invoices import service as _service  # noqa: F401
from app.invoices.nodes import (  # noqa: F401
    invoice_gate,
    invoice_issue,
    invoice_notify,
    invoice_reject,
    invoice_request,
    invoice_sweep,
    invoice_void,
    invoice_withdraw,
)
