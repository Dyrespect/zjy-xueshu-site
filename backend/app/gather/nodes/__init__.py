"""聚人的节点（07 科研绘图聚人设计第十五节）。导入本包 = 把它们登记进注册表（app/core/nodes.py）。

先导入 service：它把「一次领取」登记成能走流程的对象、把 flows/ 交给引擎。
"""

from app.gather import service as _service  # noqa: F401
from app.gather.nodes import (  # noqa: F401
    figure_pack_deliver,
    figure_release,
    figure_unlock_request,
    figure_unlock_verify,
    funnel_cta,
    funnel_track,
    skill_oss_sync,
)
