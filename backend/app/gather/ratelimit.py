"""对外接口限频：limits（MIT）的移动窗口；计数走底座的 core.ratelimit（存库或 Redis，几个网站进程共用一份）。

11-18 底座可扩展改：原来是进程内存储（MemoryStorage），开几个进程限频就松几倍、重启清零（scripts/check.py 规矩 S3）。
调用方把 app.state 传进来（请求里是 request.app.state，MCP 外壳里是建 server 时的 app.state）。
"""

from __future__ import annotations

from typing import Any


def allow(state: Any, key: str, per_hour: int) -> bool:
    """同一个键一小时内最多 per_hour 次；超了返回 False。"""
    return state.ratelimit.hit("gather", key, limit=max(per_hour, 1), window=3600)
