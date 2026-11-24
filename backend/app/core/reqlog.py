"""请求中间件：请求号贯穿、计时、每个请求一行访问日志、把这次请求的情况交给登记的观察者（docs/任务单/07_运维与数据_设计.md）。

- 请求号：客户端带了合法的 `X-Request-ID`（8–64 位字母数字和横杠）就沿用（nginx 可以先生成），否则自己生成 16 位；
  放进 app/core/log.py 的 `request_id` 上下文变量（同一次请求里打的日志都带 rid），并写回响应头 `X-Request-ID`。
- 访问日志：一行 JSON，只写方法、路由模板（`/api/delivery/{token}`，不是带令牌的原始网址）、状态码、耗时、请求号。
- 观察者：`app.state.request_observers` 里的函数，每个请求结束后各调一次，参数是 RequestInfo；运维模块的计数器就是这样挂上的。
  观察者出错只记日志，不影响请求。core 不 import 任何业务模块，谁想听谁自己往列表里加。
- 没接住的异常：记成 500，异常类型和脱敏后的摘要交给观察者，然后照样往外抛（外层 ServerErrorMiddleware 回 500）。
纯 ASGI，不包请求体，流式下载照常。
"""

from __future__ import annotations

import logging
import re
import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.core.log import request_id
from app.core.redact import redact_text

log = logging.getLogger("app.access")
_RID_RE = re.compile(r"^[A-Za-z0-9\-]{8,64}$")
_SILENT_PREFIXES = ("/assets/",)  # 静态文件不逐条写访问日志（照样计数）


@dataclass
class RequestInfo:
    method: str
    path: str  # 原始路径：只给观察者分组用（比如算页面组），不许原样写进日志或库
    route: str  # 路由模板；没匹配上的是「(没有这个地址)」
    status: int
    ms: float
    rid: str
    client: str
    user_agent: str
    accept: str
    error_kind: str = ""
    error_message: str = ""  # 已脱敏


Observer = Callable[[RequestInfo], None]


def _route_of(scope: dict[str, Any]) -> str:
    """完整的路由模板。FastAPI 0.16x 起 app.include_router(prefix=…) 不再把前缀拼进路由对象，scope["route"].path 只有后半段，
    前缀在 scope["fastapi"]["included_router"] 里；拿不到就退回前缀 + 后半段，再不行只用后半段。"""
    route = scope.get("route")
    path = getattr(route, "path", None) or getattr(route, "path_format", None)
    fa = scope.get("fastapi")
    if path and isinstance(fa, dict):
        try:
            erc = fa.get("effective_route_context")
            if getattr(erc, "path_format", ""):
                return str(erc.path_format)
            ir = fa.get("included_router")
            if ir is not None:
                return f"{ir.include_context.prefix}{path}"
        except Exception:  # noqa: BLE001  FastAPI 内部结构变了：退回后半段
            return str(path)
    if path:
        return str(path)
    if str(scope.get("path", "")).startswith("/assets/"):
        return "/assets/{file}"
    return "(没有这个地址)"


def _client_of(scope: dict[str, Any], headers: dict[str, str]) -> str:
    app = scope.get("app")
    trust = bool(getattr(getattr(getattr(app, "state", None), "settings", None), "TRUST_PROXY_HEADERS", False))
    if trust:
        cf = headers.get("cf-connecting-ip", "").strip()
        if cf:
            return cf
        first = headers.get("x-forwarded-for", "").split(",")[0].strip()
        if first:
            return first
    client = scope.get("client")
    return client[0] if client else "unknown"


class RequestContextMiddleware:
    def __init__(self, app: Any) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        incoming = headers.get("x-request-id", "")
        rid = incoming if _RID_RE.match(incoming) else secrets.token_hex(8)
        token = request_id.set(rid)
        started = time.perf_counter()
        status = 500
        error_kind = error_message = ""

        async def send_wrapper(message: dict[str, Any]) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = int(message["status"])
                message.setdefault("headers", [])
                message["headers"] = [(k, v) for k, v in message["headers"] if k.lower() != b"x-request-id"] + [
                    (b"x-request-id", rid.encode())]
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception as e:  # noqa: BLE001
            status = 500
            error_kind = type(e).__name__
            error_message = redact_text(str(e))[:300]
            raise
        finally:
            ms = (time.perf_counter() - started) * 1000
            path = str(scope.get("path", ""))
            info = RequestInfo(
                method=str(scope.get("method", "")), path=path, route=_route_of(scope), status=status, ms=ms, rid=rid,
                client=_client_of(scope, headers), user_agent=headers.get("user-agent", "")[:300],
                accept=headers.get("accept", "")[:200], error_kind=error_kind, error_message=error_message,
            )
            if not path.startswith(_SILENT_PREFIXES):
                level = logging.ERROR if status >= 500 else logging.INFO
                log.log(level, "%s %s %s %.0fms", info.method, info.route, status, ms, extra={
                    "http_method": info.method, "route": info.route, "status": status, "ms": round(ms, 1),
                    **({"error_kind": error_kind} if error_kind else {})})
            app = scope.get("app")
            for fn in list(getattr(getattr(app, "state", None), "request_observers", []) or []):
                try:
                    fn(info)
                except Exception:  # noqa: BLE001  观察者出错不影响请求
                    log.exception("请求观察者出错")
            request_id.reset(token)


def add_observer(app: Any, fn: Observer) -> None:
    obs = getattr(app.state, "request_observers", None)
    if obs is None:
        obs = []
        app.state.request_observers = obs
    if fn not in obs:
        obs.append(fn)


def remove_observer(app: Any, fn: Observer) -> None:
    obs = getattr(app.state, "request_observers", None) or []
    if fn in obs:
        obs.remove(fn)
