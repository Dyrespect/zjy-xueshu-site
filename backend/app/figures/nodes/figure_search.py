"""figure.search 图库检索：网站搜索框、开放接口、插件、skill 在线模式共用这一个节点。"""

from __future__ import annotations

from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register
from app.figures.node_models import SearchIn
from app.figures.schemas import SearchOut
from app.figures.search_service import run_search


def handler(call: NodeCall, data: SearchIn) -> NodeResult:
    lib = getattr(call.ctx, "figure_library", None)
    if lib is None:
        return NodeResult(exit="off", detail="图库没加载起来")
    body = run_search(call.db, lib, call.ctx.figure_cache, data.q, data.code,
                      caller=data.caller, src=data.src, visitor=data.visitor, client=data.client)
    out = SearchOut.model_validate(body)
    if out.total == 0:
        return NodeResult(exit="empty", output=out, detail="一张都没找到")
    if lib.engine.semantic and not body.get("_used_vectors", True):
        return NodeResult(exit="degraded", output=out)
    return NodeResult(exit="ok", output=out)


CARD = NodeCard(
    id="figure.search",
    name="图库检索",
    description="一句话找图：猜图型、拆词、分几路给这一类的图和别的类里画同一样东西的；库里没有某个词就直说并补找相近的。"
                "网站搜索框、开放接口、插件（MCP）、skill 在线模式都调这一个节点；下架的图不出现。",
    category="获客",
    tech=["FastAPI GET /api/figures/search（网站）", "app/figures/search_service.run_search + 查参考.py v2.1（engine.py 加载，只读）",
          "向量小服务 EMBED_URL（连不上退关键词）", "表 search_logs（加 caller、src、visitor、client 四列）",
          "ctx 要有 figure_library、figure_cache（app.state 上的，见 figures/overlay.FiguresCtx）"],
    input_model=SearchIn,
    output_model=SearchOut,
    exits=[
        NodeExit(key="ok", label="有结果", kind="ok"),
        NodeExit(key="empty", label="一张都没找到", kind="ok"),
        NodeExit(key="degraded", label="向量没用上、只按关键词", kind="ok"),
        NodeExit(key="off", label="图库没加载（接口回 503）", kind="fail"),
    ],
    config=["FIGURE_EMBED_TIMEOUT：向量超时秒数", "FIGURE_ASSET_BASE：预览图走对象存储时的网址前缀"],
    emits=["无（每次搜索记一行 search_logs）"],
    listens=["无"],
    replaceable=["检索引擎（查参考.py 以后的版本）", "向量服务（mini / 服务器 / 百炼重编）"],
    failure="只读、天然幂等；向量超时退关键词；同一句话 30 分钟内走缓存（下架、改标签后缓存清空）。",
    owner="L",
    status="要改",
)
register(CARD, handler)
