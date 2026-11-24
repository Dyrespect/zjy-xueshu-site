"""底座可扩展的测试共用：N 个线程同时打同一件事（各自一个库连接、各自一个事务，跟 N 个请求 / N 个 worker 一样）。

两种库都跑：默认 SQLite；TEST_DATABASE_URL 指向 PostgreSQL 时同一批测试跑在 PG 上（tests/conftest.py）。
"""

from __future__ import annotations

import threading
import traceback
from collections.abc import Callable
from typing import Any


def run_at_once(fns: list[Callable[[], Any]], *, timeout: float = 60.0) -> list[Any]:
    """几个函数在几个线程里同时开跑（Barrier 对齐起跑线）。返回每个的结果；抛的异常原样放在结果里。"""
    barrier = threading.Barrier(len(fns))
    out: list[Any] = [None] * len(fns)

    def go(i: int, fn: Callable[[], Any]) -> None:
        try:
            barrier.wait(timeout=timeout)
            out[i] = fn()
        except Exception as e:  # noqa: BLE001 - 交给测试判断
            e.trace = traceback.format_exc()  # type: ignore[attr-defined]
            out[i] = e

    threads = [threading.Thread(target=go, args=(i, fn), daemon=True) for i, fn in enumerate(fns)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout)
        assert not t.is_alive(), "有线程卡住了（死锁？）"
    return out


def no_errors(results: list[Any]) -> list[Any]:
    errs = [r for r in results if isinstance(r, Exception)]
    assert not errs, "并发时有线程出错：\n" + "\n".join(getattr(e, "trace", repr(e)) for e in errs)
    return results
