"""交付这一块的运行时：本模块的设置放哪（节点、后台圈、接口都从这里取）。

app 启动时（delivery/router.py 的 lifespan）按 `app.state.delivery_settings`（测试里设）或读 .env 配好；
没起 app 的地方（脚本、单测直接调节点）按环境变量建一份，不读仓库根的 .env。
"""

from __future__ import annotations

from app.delivery.settings import DeliverySettings

_SETTINGS: DeliverySettings | None = None


def configure(settings: DeliverySettings | None) -> DeliverySettings:
    global _SETTINGS
    _SETTINGS = settings or DeliverySettings()
    return _SETTINGS


def get_settings() -> DeliverySettings:
    global _SETTINGS
    if _SETTINGS is None:
        _SETTINGS = DeliverySettings(_env_file=None)
    return _SETTINGS


def reset() -> None:
    """app 关的时候清掉（测试一个接一个起 app，前一个的设置不能漏给后一个）。"""
    global _SETTINGS
    _SETTINGS = None
