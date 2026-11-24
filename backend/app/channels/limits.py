"""入口用的限流：用底座的限流器（app.state.ratelimit，app/core/ratelimit.py：计数在库里或 Redis，几个网站进程看到同一份）。

接口：hit(bucket, key, limit=, window=) / count(bucket, key, window) / add(bucket, key)。
（入口先写的时候底座还没合进来，这里有过一个进程内存的替身；11-18 合并底座可扩展后删掉了，规矩 S3 不许进程内存计数。）
"""

from __future__ import annotations

from typing import Any, Protocol


class Limiter(Protocol):
    def hit(self, bucket: str, key: str, *, limit: int, window: float) -> bool: ...

    def count(self, bucket: str, key: str, window: float) -> int: ...

    def add(self, bucket: str, key: str) -> None: ...


def limiter(app: Any) -> Limiter:
    return app.state.ratelimit
