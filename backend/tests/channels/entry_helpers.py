"""入口模块（D）测试共用：建 app（后台圈关掉、手动跑）、发码、开微信客服、假邮箱、数模型调用。

不发任何真请求：企业微信用 tests/channels/fake_wecom.py，模型用 PydanticAI 的 FunctionModel，邮件记在列表里。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from app.channels.entry_config import EntryConfig, load_entry_config, save_entry_config
from app.channels.settings import ChannelsSettings
from app.core.db import Database
from app.core.migrate import upgrade_to_heads
from tests.channels.fake_wecom import CORPID, KFID, SECRET
from tests.conftest import make_settings
from tests.intake.helpers import make_app

OFFICIAL_TOKEN = "QDG6eK"
OFFICIAL_AES = "jWmYm7qr5nMoAUwZRjGtBxmz3KA1tkAj3ykkR6q2B2C"
REDEEM_LINK = "https://work.weixin.qq.com/kf/kfcfake?enc_scene=ENCredeem"


class FakeMail:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    def __call__(self, to: str, subject: str, text: str) -> None:
        self.sent.append({"to": to, "subject": subject, "text": text})

    def last_code(self) -> str:
        import re

        return re.search(r"验证码是 (\d{6})", self.sent[-1]["text"]).group(1)


class CountingModel:
    """数模型被调了几次的假模型（访客上限、欢迎语不许花模型钱）。"""

    def __init__(self, reply: str = "好的") -> None:
        self.calls = 0
        self.reply = reply

        def fn(messages: list[Any], info: AgentInfo) -> ModelResponse:
            self.calls += 1
            return ModelResponse(parts=[TextPart(self.reply)])

        self.model = FunctionModel(fn, model_name="数次数的假模型")


def wecom_settings(tmp_path: Path, **over: Any):
    s = make_settings(tmp_path, WECOM_CORPID=CORPID, WECOM_KF_SECRET=SECRET, WECOM_TOKEN=OFFICIAL_TOKEN,
                      WECOM_AES_KEY=OFFICIAL_AES, WECOM_OPEN_KFID=KFID, **over)
    upgrade_to_heads(s.DATABASE_URL)
    return s


def entry_app(settings, notifier, tmp_path: Path, *, model: Any = None, wecom: Any = None, mail: FakeMail | None = None,
              **channels_over: Any):
    app = make_app(settings, notifier, tmp_path, model=model, wecom_transport=wecom.transport() if wecom else None)
    app.state.channels_settings = ChannelsSettings(_env_file=None, CHANNELS_DISPATCH=False, CHANNELS_TICK=False,
                                                   WECOM_API_BASE="https://qyapi.test/cgi-bin", **channels_over)
    if mail is not None:
        app.state.email_sender = mail
    return app


def set_entry(app, **changes: Any) -> EntryConfig:
    """改入口设置（另开一个库连接，不提前建运行时）。"""
    d = Database(app.state.settings.DATABASE_URL)
    with d.session() as db:
        cfg = load_entry_config(db).model_copy(update=changes)
        save_entry_config(db, cfg)
    d.dispose()
    return cfg


def enable_wecom(app) -> None:
    set_entry(app, wecom_enabled=True, wecom_links={"redeem": REDEEM_LINK})


def pool_code(db, sku: str = "regular-p1", addons: tuple[str, ...] = ()) -> str:
    """码池里没卖出的码（发卡站、闲鱼那种，认领时才建单）。"""
    from app.intake import codes

    return codes.generate_batch(db, sku=sku, count=1, addons=list(addons))[1][0].code


def paid_code(db, ctx, sku: str = "regular-p1", platform: str = "web") -> tuple[str, int]:
    """付款时就建了单的码（自有网页、平台）。返回（码, 订单号）。"""
    from app.core.nodes import NodeCall, run_node
    from app.intake import flow

    flow.ensure_nodes()
    import secrets

    res = run_node("order.create", NodeCall(db, ctx, "shop"), {
        "platform": platform, "platform_order_id": f"T{secrets.token_hex(4)}", "sku": sku, "addons": [],
        "buyer_id": "", "paid_amount": "", "raw_ref": "", "source": ""})
    return res.output.code, res.output.order_id
