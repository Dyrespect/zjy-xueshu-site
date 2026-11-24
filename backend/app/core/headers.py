"""统一加的响应头（生产加固）。纯 ASGI 中间件，不包请求体，流式下载、文件响应照常。

- 不缓存（Cache-Control: no-store）：后台、登录、交付页、网页聊天、工厂领交接包的接口。
  这些返回里有客户的对话、材料、成品，不能让 Cloudflare 或浏览器缓存下来。
- 不让搜索引擎收（X-Robots-Tag: noindex, nofollow）：交付页 /d/*、后台 /admin*、网页聊天 /chat*
  （页面是前端兜底路由给的 index.html，接口在上面那几个前缀下）。
- 带随机令牌的页面（/d/<令牌>、/chat/<key>）加 Referrer-Policy: no-referrer，点外链时令牌不会跟着 Referer 漏出去。
- 前端构建产物 /assets/*（文件名带内容哈希）可以长缓存：public, max-age=1 年, immutable。
- 所有响应加 X-Content-Type-Options: nosniff。
路径前缀是网址规则，不 import 业务模块（core 不依赖业务模块）。
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, MutableMapping
from typing import Any

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
ASGIApp = Callable[[Scope, Callable[[], Awaitable[Message]], Callable[[Message], Awaitable[None]]], Awaitable[None]]

# /c/{码} 兑换页、/me 我的订单（入口模块 D）：地址里带激活码、登录凭证，跟 /d、/chat 一样不缓存、不收录、不带 Referer
NO_STORE_PREFIXES = ("/api/admin", "/api/auth", "/api/delivery", "/api/channels/web", "/api/channels/redeem",
                     "/api/channels/account", "/api/channels/login", "/api/handoffs")
# /login 登录页（12 号设计）：不收录
NOINDEX_PREFIXES = ("/d", "/admin", "/chat", "/c", "/me", "/login", "/api/delivery", "/api/admin", "/api/channels/web")
TOKEN_PAGE_PREFIXES = ("/d", "/chat", "/c", "/me")
IMMUTABLE_PREFIXES = ("/assets",)


def _under(path: str, prefixes: tuple[str, ...]) -> bool:
    """按整段匹配：/admin 和 /admin/xxx 算，/administer 不算。"""
    return any(path == p or path.startswith(p + "/") for p in prefixes)


def headers_for(path: str) -> list[tuple[bytes, bytes]]:
    out: list[tuple[bytes, bytes]] = [(b"x-content-type-options", b"nosniff")]
    if _under(path, NO_STORE_PREFIXES):
        out.append((b"cache-control", b"no-store"))
    elif _under(path, IMMUTABLE_PREFIXES):
        out.append((b"cache-control", b"public, max-age=31536000, immutable"))
    if _under(path, NOINDEX_PREFIXES):
        out.append((b"x-robots-tag", b"noindex, nofollow"))
    if _under(path, TOKEN_PAGE_PREFIXES):
        out.append((b"referrer-policy", b"no-referrer"))
    return out


class SecurityHeadersMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        extra = headers_for(scope.get("path", ""))
        replace = {k for k, _ in extra}

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                kept = [(k, v) for k, v in message.get("headers", []) if k.lower() not in replace]
                message["headers"] = kept + extra
            await send(message)

        await self.app(scope, receive, send_with_headers)
