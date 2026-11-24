"""本模块的运行时：配置、假网关的账本、给网关客户端用的 transport（测试里换成假的，不联网）。限流在 core.ratelimit（不在进程内存）。

节点拿它的办法：调节点时传 ShopCtx（= 接单的 Ctx + .shop）。ShopCtx 把别的属性原样转给接单的 Ctx，
所以订单中枢的节点（order.create、confirm.receipt……）拿到它照常用 notifier、settings、public_base_url。
测试里在进 lifespan 之前设 app.state.shop_settings（_env_file=None）、app.state.shop_transports（{"wechat": …, "alipay": …}）。
"""

from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass, field
from typing import Any

from fastapi import FastAPI, Request

from app.intake.runtime import get_runtime
from app.shop.settings import ShopSettings


@dataclass
class ShopRuntime:
    settings: ShopSettings
    fake_secret: str
    transports: dict[str, Any] = field(default_factory=dict)  # "wechat" / "alipay" → httpx transport（测试用）
    # 假网关的账本：商户订单号 → 状态。只在 SHOP_FAKE_PAY（测试、本机走查）用，生产启动即拒（router.lifespan）；
    # 多进程跑假网关时设 SHOP_FAKE_SECRET，通知验签各进程一致
    fake_trades: dict[str, dict[str, Any]] = field(default_factory=dict)
    lock: threading.Lock = field(default_factory=threading.Lock)
    app_env: str = "dev"  # 底座的 APP_ENV：prod 时假网关一律不出（启动时也拦，见 router.lifespan）


class ShopCtx:
    """接单的 Ctx + 本模块运行时。只读代理：属性都转给接单的 Ctx，多一个 .shop。"""

    def __init__(self, base: Any, shop: ShopRuntime) -> None:
        self._base = base
        self.shop = shop

    def __getattr__(self, name: str) -> Any:
        return getattr(self._base, name)


def get_shop(app: FastAPI) -> ShopRuntime:
    rt = getattr(app.state, "shop", None)
    if rt is None:
        s: ShopSettings = getattr(app.state, "shop_settings", None) or ShopSettings()
        secret = s.SHOP_FAKE_SECRET.get_secret_value() or secrets.token_hex(16)
        base = getattr(app.state, "settings", None)
        rt = ShopRuntime(settings=s, fake_secret=secret, transports=dict(getattr(app.state, "shop_transports", None) or {}),
                         app_env=getattr(base, "APP_ENV", "dev"))
        app.state.shop = rt
    return rt


def shop_ctx(app: FastAPI) -> ShopCtx:
    return ShopCtx(get_runtime(app).ctx, get_shop(app))


def shop_ctx_dep(request: Request) -> ShopCtx:
    return shop_ctx(request.app)
