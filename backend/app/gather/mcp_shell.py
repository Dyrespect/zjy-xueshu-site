"""插件的远程 MCP 外壳：用官方 mcp Python SDK（MIT，MCPServer + 可流式 HTTP，无状态、JSON 回复），不自己实现协议。

- 地址：POST /api/gather/mcp（图库域名上可以让 nginx 把 /mcp 转过来）。Claude「连接器」、Cherry Studio、Cursor、Trae、
  Claude Code（claude mcp add --transport http <名字> <地址>）填这一个网址就能用。
- 三个工具 find_figures / figure_types / figure_detail，底下是 figure.ai_tool → figure.search（和网站、开放接口同一个节点）。
- 每个 app 一份 MCPServer（测试里会建很多个 app）：lifespan 里建好、跑 session_manager，挂在 app.state.gather_mcp；
  路由上是一个很薄的转发（_Shim），按 scope["app"] 找到这一份。
- 公开、只读、不用登录：关掉 SDK 给本机服务准备的 DNS 重绑定防护（它只认 localhost 的 Host，线上域名会被拒）。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from mcp.server.mcpserver import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import PlainTextResponse
from starlette.routing import Route

from app.core.nodes import NodeCall, NodeError, run_node
from app.gather import ratelimit
from app.gather.config import DEFAULTS, load_config
from app.gather.runtime import GatherCtx
from app.gather.settings import GatherSettings
from app.gather.site import order_url

PATH = "/api/gather/mcp"
INSTRUCTIONS = "心理学科研图库：find_figures 一句话找论文里的图，结果里每张都有出处和网站详情页链接，请把链接和出处一起给用户。"


def _text(out: Any) -> str:
    if out.op == "types":
        lines = [f"{t.code} {t.name}" for t in out.types]
    else:
        lines = [f"猜的图型：{out.guess}"] if out.guess else []
        for i, it in enumerate(out.items, 1):
            lines.append(f"{i}. {it.what}（{it.type_name}，{it.journal} {it.year}）\n   预览图：{it.preview_url}\n"
                         f"   详情页：{it.page_url}\n   出处：{it.cite}")
        if not out.items:
            lines.append("没找到合适的图。")
        if out.more_url:
            lines.append(f"网站上看更多：{out.more_url}")
    if out.note:
        lines.append(out.note)
    return "\n".join(lines)


def build_server(app: FastAPI) -> MCPServer:
    st = app.state

    def run(args: dict[str, Any]) -> str:
        gs: GatherSettings = getattr(st, "gather_settings", None) or GatherSettings()
        figures_url = gs.SITE_FIGURES_URL.strip().rstrip("/")
        if not ratelimit.allow(st, "open:mcp", gs.OPEN_API_RATE_PER_HOUR * 20):  # 拿不到客户端 IP，按整条外壳给一个总上限
            return f"今天查得太多了，去网站上接着找：{figures_url or '图库网站'}"
        with st.db.session() as db:
            cfg = load_config(db)
            note = cfg["ai_note"].replace("{figures_url}", figures_url).replace("{order_url}", order_url(gs, "ai"))
            ctx = GatherCtx(gs, st.storage, st.notifier, getattr(st, "figure_library", None),
                            getattr(st, "figure_cache", None), figures_url, note, cfg)
            try:
                res = run_node("figure.ai_tool", NodeCall(db, ctx, "ai:mcp"), {**args, "caller": "ai", "client": "mcp"})
            except NodeError as e:
                return f"参数不对：{e}"
        if res.exit == "off":
            return "图库暂时打不开，请稍后再试。"
        if res.exit == "not_found":
            return "没有这张图。"
        return _text(res.output)

    try:  # 插件名字（后台聚人设置；改了以后重启生效）。库还没迁移时用默认值，不挡启动
        with st.db.session() as db:
            name = load_config(db)["plugin_name"]
    except Exception:
        name = DEFAULTS["plugin_name"]
    server = MCPServer(name="psyengine-figures", title=name, instructions=INSTRUCTIONS, version="1")

    @server.tool(description="按一句话在心理学科研图库里找论文图（方法图、结果图、模型图……），返回带出处和网站详情页的图。"
                             "q 写想画什么，如「有调节的中介模型」；code 是图型代号（可选，先调 figure_types）；n 要几张（1–20）。")
    def find_figures(q: str, code: str | None = None, n: int = 12) -> str:
        return run({"op": "find", "q": q[:200], "code": code or None, "n": min(max(int(n), 1), 20)})

    @server.tool(description="列出图库里有哪些图型（代号和名字）。")
    def figure_types() -> str:
        return run({"op": "types"})

    @server.tool(description="看一张图的出处、预览图和网站详情页。")
    def figure_detail(id: int) -> str:  # noqa: A002 工具参数名对外就叫 id
        return run({"op": "figure", "id": int(id)})

    return server


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    server = build_server(app)
    asgi = server.streamable_http_app(
        streamable_http_path=PATH, stateless_http=True, json_response=True,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
    )
    async with server.session_manager.run():
        app.state.gather_mcp = asgi
        try:
            yield
        finally:
            app.state.gather_mcp = None


class _Shim:
    """路由上的转发：找到这个 app 的那一份 MCP（lifespan 里建的）。"""

    async def __call__(self, scope, receive, send) -> None:
        asgi = getattr(scope["app"].state, "gather_mcp", None)
        if asgi is None:
            await PlainTextResponse("插件还没启动好", status_code=503)(scope, receive, send)
            return
        await asgi(scope, receive, send)


route = Route("/mcp", endpoint=_Shim(), methods=["GET", "POST", "DELETE"], include_in_schema=False)
