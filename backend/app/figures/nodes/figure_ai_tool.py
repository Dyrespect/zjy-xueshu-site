"""figure.ai_tool 插件（对外名字在后台设置里，默认「PsyEngine 图库插件」）：开放接口、MCP、skill 在线模式三个外壳共用。"""

from __future__ import annotations

from urllib.parse import quote

from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register, run_node
from app.figures.node_models import FindIn, FindItem, FindOut, SearchIn
from app.figures.schemas import TypeRef

FROM = {"open": "ai", "ai": "ai", "skill": "skill"}  # 链接里的 from（来源白名单 FUNNEL_SOURCES 里的值）


def _abs(base: str, url: str) -> str:
    return f"{base}{url}" if url.startswith("/") else url


def _item(lib, base: str, fid: int, src: str) -> FindItem | None:
    d = lib.detail(fid)
    if d is None or not d.get("cite"):
        return None  # 没有出处的图不返回（07 第十一节检查 7）
    return FindItem(
        id=fid, what=d["title"], type_code=d["type_code"], type_name=d["type_name"], journal=d["journal"],
        year=d["year"], cite=d["cite"], preview_url=_abs(base, d["preview_url"]), thumb_url=_abs(base, d["thumb_url"]),
        page_url=f"{base}/figure/{fid}?from={src}",
    )


def handler(call: NodeCall, data: FindIn) -> NodeResult:
    lib = getattr(call.ctx, "figure_library", None)
    if lib is None:
        return NodeResult(exit="off", detail="图库没加载起来")
    base = (getattr(call.ctx, "figures_url", "") or "").rstrip("/")
    note = getattr(call.ctx, "ai_note", "") or ""
    src = FROM[data.caller]
    if data.op == "types":
        types = [TypeRef(code=c, name=n) for c, n in lib.engine.names.items()]
        return NodeResult(exit="ok", output=FindOut(op="types", types=types, note=note))
    if data.op == "figure":
        item = _item(lib, base, data.id or 0, src)
        if item is None:
            return NodeResult(exit="not_found", output=FindOut(op="figure", note=note), detail="没有这张图")
        return NodeResult(exit="ok", output=FindOut(op="figure", items=[item], note=note))
    if not data.q.strip():
        return NodeResult(exit="empty", output=FindOut(op="find", note=note), detail="没写要找什么")
    res = run_node("figure.search", call, SearchIn(q=data.q, code=data.code, caller=data.caller, src=src,
                                                    client=data.client))
    if res.exit == "off":
        return NodeResult(exit="off", detail=res.detail)
    s = res.output
    seen: set[int] = set()
    items: list[FindItem] = []
    for g in s.groups:
        for c in g.cards:
            if c.id in seen or len(items) >= data.n:
                continue
            seen.add(c.id)
            it = _item(lib, base, c.id, src)
            if it is not None:
                items.append(it)
    out = FindOut(op="find", query=s.query, guess=s.guess.name if s.guess else "", items=items,
                  more_url=f"{base}/search?q={quote(s.query)}&from={src}", note=note)
    return NodeResult(exit="ok" if items else "empty", output=out)


CARD = NodeCard(
    id="figure.ai_tool",
    name="插件：接到你的 AI",
    description="让研究生自己的 AI（Claude、Cherry Studio、Cursor、Trae、Claude Code……）直接查图库：说一句「有调节的中介模型怎么画」，"
                "拿回十几张带出处、带网站详情页链接的图。一个地址三个外壳：开放接口、远程 MCP、skill 在线模式，底下都是 figure.search。不收费、限频。",
    category="获客",
    tech=["开放接口 GET /api/gather/open/v1/find|types|figure/{id}（OpenAPI 文档 /api/gather/open/v1/openapi.json）",
          "远程 MCP POST /api/gather/mcp（无状态 JSON-RPC：initialize、tools/list、tools/call，手写，不加依赖）",
          "skill 在线模式：开源仓库里的 脚本/在线查图.py 调开放接口", "调 run_node('figure.search')"],
    input_model=FindIn,
    output_model=FindOut,
    exits=[
        NodeExit(key="ok", label="有结果", kind="ok"),
        NodeExit(key="empty", label="没找到（给网站搜索地址）", kind="ok"),
        NodeExit(key="not_found", label="没有这张图", kind="fail"),
        NodeExit(key="off", label="图库没加载", kind="fail"),
    ],
    config=["plugin_name：对外名字（后台「聚人设置」，默认 PsyEngine 图库插件）", "ai_note：每次返回末尾那行字",
            "OPEN_API_RATE_PER_HOUR：每个 IP 每小时次数"],
    emits=["无（figure.search 记 search_logs，caller=open/ai/skill，client 写客户端名）"],
    listens=["无"],
    replaceable=["远程 MCP", "开放接口（扣子、GPTs Actions 这类）", "skill 在线模式——三个外壳，底下同一个 figure.search"],
    failure="只读、幂等；超频回 429 和一句人话（去网站接着找）；没有出处的图不返回；下架的图不返回。",
    owner="L",
    status="要新做",
)
register(CARD, handler)
