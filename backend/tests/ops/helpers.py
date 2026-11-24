"""运维测试共用：建 app（定时关掉、外部检查走假传输层、不连外网、不读 .env）、登录、造订单、造计数。"""

from __future__ import annotations

import io
import json
import logging
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException

from app.core.log import JsonFormatter
from app.main import create_app
from app.ops.settings import OpsSettings
from tests.conftest import TEST_PASSWORD

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15"


def fake_hook() -> str:
    """假的飞书 webhook 地址（拼出来的，仓库里不出现完整的样子；scripts/check.py 规矩 4 会拦完整的）。"""
    return "https://open.feishu.cn/open-apis/bot/v2/" + "hook/" + "0f1e2d3c-" + "4b5a-6978-8a9b-" + "0c1d2e3f4a5b"


class Recorder:
    """假的外部服务：记下每个请求，按网址回话。"""

    def __init__(self, feishu_code: int = 0, down: tuple[str, ...] = ()) -> None:
        self.requests: list[httpx.Request] = []
        self.feishu_code = feishu_code
        self.down = down

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host = request.url.host
        if any(d in host for d in self.down):
            raise httpx.ConnectError("连不上", request=request)
        if "feishu" in host:
            return httpx.Response(200, json={"code": self.feishu_code, "msg": "success" if self.feishu_code == 0 else "sign match fail"})
        return httpx.Response(200, text="ok")

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def feishu_bodies(self) -> list[dict[str, Any]]:
        return [json.loads(r.content) for r in self.requests if "feishu" in r.url.host]


def ops_app(settings, notifier, *, recorder: Recorder | None = None, cert_days: int | None = None, disk_pct: float = 50.0,
            **over: Any) -> FastAPI:
    app = create_app(settings, notifier=notifier)
    values: dict[str, Any] = dict(OPS_TIMER_ENABLED=False, OPS_EXTERNAL_CHECKS=False, OPS_SENDER="core_notifier",
                                  OPS_HEALTH_CACHE_SECONDS=0, OPS_BACKUP_DIR=settings.DATA_DIR / "backups")
    values.update(over)
    app.state.ops_settings = OpsSettings(_env_file=None, **values)
    app.state.ops_transport = (recorder or Recorder()).transport()
    if cert_days is not None:
        app.state.ops_cert_probe = lambda host, timeout: cert_days
    total = 100 * 10**9  # 假磁盘 100 GB，用了 disk_pct%（不看这台机器真实的磁盘）
    app.state.ops_disk_probe = lambda path: SimpleNamespace(total=total, used=total * disk_pct / 100, free=total * (1 - disk_pct / 100))
    # 测试用的两个接口：一个正常、一个必定 500（看计数、看告警）
    app.add_api_route("/api/_ok", lambda: {"ok": True}, methods=["GET"])

    def boom() -> None:
        raise RuntimeError("测试用的错误 13812345678")

    app.add_api_route("/api/_boom", boom, methods=["GET"])

    def teapot() -> None:
        raise HTTPException(503, detail="忙")

    app.add_api_route("/api/_busy", teapot, methods=["GET"])
    return app


def login(c) -> None:
    assert c.post("/api/auth/login", json={"password": TEST_PASSWORD}).status_code == 200


def make_order(db, *, paid: str = "29.90", stage: str = "paid", **kw: Any) -> Any:
    from app.intake.models import Order

    o = Order(delivery_token=secrets.token_urlsafe(24), paid_amount=paid, stage=stage, platform="web", **kw)
    db.add(o)
    db.flush()
    return o


class LogCapture:
    """把根日志按线上的 JSON 格式写进内存（看格式化之后的真样子，含脱敏）。"""

    def __init__(self) -> None:
        self.buf = io.StringIO()
        self.handler = logging.StreamHandler(self.buf)
        self.handler.setFormatter(JsonFormatter())
        from app.core.log import _RequestIdFilter

        self.handler.addFilter(_RequestIdFilter())

    def __enter__(self) -> "LogCapture":
        logging.getLogger().addHandler(self.handler)
        return self

    def __exit__(self, *a: Any) -> None:
        logging.getLogger().removeHandler(self.handler)

    @property
    def text(self) -> str:
        return self.buf.getvalue()

    def lines(self) -> list[dict[str, Any]]:
        return [json.loads(x) for x in self.text.splitlines() if x.strip()]


def utc(*a: int) -> datetime:
    return datetime(*a, tzinfo=timezone.utc)


def minutes_ago(n: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=n)


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path
