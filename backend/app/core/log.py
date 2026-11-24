"""日志：每行一条 JSON（上线时由 docker / 进程管理器收集），带请求号，写出去之前统一脱敏。

- 格式化用现成的 python-json-logger（BSD-2）；我们只加两样：请求号、脱敏（app/core/redact.py）。
- `LOG_FORMAT=json`（默认）每行 `{"ts","level","logger","msg","rid",…}`；`text` 是给人在终端里看的老格式（同样脱敏）。
- 请求号：中间件（app/core/reqlog.py）把这次请求的号放进 `request_id` 这个上下文变量，同一次请求里打的每一行日志都带上 `rid`。
- 想多记几个字段：`log.info("说明", extra={"order": 12, "ms": 30})`，键名敏感的（phone、token、code、content……）整个打码。
- uvicorn 自带的访问日志（会写原始网址，里面有交付页令牌）和 httpx 的请求日志（会写飞书 webhook 整个网址）降到 WARNING，
  访问日志改由中间件写，只写路由模板（docs/任务单/07_运维与数据_设计.md 第六节冲突 2）。
- `LOG_FILE` 有值时另外写一份到文件（logrotate 样例在 deploy/ops/logrotate-psyppt.conf）。
"""

from __future__ import annotations

import logging
from contextvars import ContextVar
from pathlib import Path
from typing import Any

from pythonjsonlogger.json import JsonFormatter as _JsonFormatter

from app.core.redact import redact, redact_text

request_id: ContextVar[str] = ContextVar("request_id", default="")

_TEXT_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"
# 这些库自己会把整条网址写进 INFO 日志
_QUIET = ("uvicorn.access", "httpx", "httpx2", "httpcore", "hpack", "urllib3", "qcloud_cos")


class _RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "rid", ""):
            record.rid = request_id.get()
        return True


class JsonFormatter(_JsonFormatter):
    def __init__(self) -> None:
        super().__init__("%(levelname)s %(name)s %(message)s", timestamp="ts", json_ensure_ascii=False,
                         rename_fields={"levelname": "level", "name": "logger", "message": "msg"})

    def process_log_record(self, log_data: dict[str, Any]) -> dict[str, Any]:
        if not log_data.get("rid"):
            log_data.pop("rid", None)
        msg = log_data.pop("msg", "")
        exc = log_data.pop("exc_info", None)
        out: dict[str, Any] = {"msg": redact_text(msg), **redact(log_data)}
        if exc:
            out["exc_info"] = redact_text(exc)[-4000:]
        return out


class RedactingTextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        text = redact_text(super().format(record))
        rid = getattr(record, "rid", "")
        return f"{text} rid={rid}" if rid else text


def _handler(h: logging.Handler, formatter: logging.Formatter) -> logging.Handler:
    h.setFormatter(formatter)
    h.addFilter(_RequestIdFilter())
    h._app_handler = True  # type: ignore[attr-defined]
    return h


def setup_logging(level: str = "INFO", fmt: str = "json", file: Path | str | None = None) -> None:
    root = logging.getLogger()
    # 根上别人挂的往终端写的 handler（比如同一个进程里先跑了迁移，alembic.ini 挂的那个不脱敏）一律换成我们的；
    # pytest 抓日志用的 handler 留着
    for h in list(root.handlers):
        if getattr(h, "_app_handler", False) or (isinstance(h, logging.StreamHandler) and not type(h).__module__.startswith("_pytest")):
            root.removeHandler(h)
    root.addHandler(_handler(logging.StreamHandler(), JsonFormatter() if fmt == "json" else RedactingTextFormatter(_TEXT_FORMAT)))
    if file:
        path = Path(file)
        path.parent.mkdir(parents=True, exist_ok=True)
        # 轮转交给 logrotate（copytruncate），不在进程里转
        root.addHandler(_handler(logging.FileHandler(path, encoding="utf-8"), JsonFormatter()))
    root.setLevel(level.upper())
    # uvicorn 自己挂了 handler、不往上传：改成往上传，走同一个格式和脱敏
    for name in ("uvicorn", "uvicorn.error"):
        lg = logging.getLogger(name)
        lg.handlers.clear()
        lg.propagate = True
    for name in _QUIET:
        logging.getLogger(name).setLevel(logging.WARNING)
