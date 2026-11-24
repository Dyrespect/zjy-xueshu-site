"""发送层（可换）：把一条运维消息（OpsMessage）发出去。节点 ops.send 按 OPS_SENDER 选实现。

- feishu_webhook：飞书群自定义机器人（单向），发 post 富文本（标题 + 段落 + 可点的链接）；开了签名校验就带签名。
  地址从 OPS_FEISHU_WEBHOOK_FILE 指的文件读（第一行地址、第二行签名密钥，可省）或 OPS_FEISHU_WEBHOOK。
- feishu_app：飞书应用机器人（底座 FEISHU_APP_FILE，现在是 Ruler，私聊发给 Edison），同样发 post 富文本（标题 + 段落 + 链接），
  文字先脱敏；和业务通知共用一个客户端（同一份令牌缓存、同一个发送节奏）。当场发（要知道发没发出去），不走业务通知的每小时上限
  （告警自己有 push.max_per_hour，日报一天一条）。
- core_notifier：走现有的通知接口（app.core.notify，底座 FEISHU_WEBHOOK），拼成纯文字发。
  运维有自己的推送规则（哪些级别推、静默、每小时上限都在后台「运维 → 设置」），所以绕过业务通知那层策略，直接用里面的发法。
- log：没配地址时用它：只写一行日志（不含消息正文以外的东西），不报错。

**webhook 地址、应用的 App Secret 和令牌是密钥**：不进日志、不进事件、不进库（scripts/check.py 规矩 19）；发送失败只记飞书回的错误码和说明。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import httpx

from app.core.notify import FeishuAppClient, FeishuAppNotifier, FeishuNotifier, LogNotifier, Notifier, unwrap
from app.core.redact import redact_text
from app.ops.models_io import OpsMessage, SendOut
from app.ops.settings import OpsSettings

log = logging.getLogger("app.ops.sender")


class Sender(ABC):
    name = "base"

    @abstractmethod
    def send(self, msg: OpsMessage) -> SendOut:
        """发一条；失败返回 delivered=False，不抛异常。"""

    @property
    def configured(self) -> bool:
        return True


class LogSender(Sender):
    name = "log"

    def send(self, msg: OpsMessage) -> SendOut:
        log.info("运维消息（没配飞书机器人，只写日志）：%s", msg.title)
        return SendOut(sender=self.name, delivered=False, detail="没配飞书机器人，只写了日志")

    @property
    def configured(self) -> bool:
        return False


class CoreNotifierSender(Sender):
    name = "core_notifier"

    def __init__(self, notifier: Notifier) -> None:
        self.notifier = notifier

    def send(self, msg: OpsMessage) -> SendOut:
        ok = self.notifier.send(msg.text(), level="urgent", kind="运维")
        return SendOut(sender=self.name, delivered=ok, detail="" if ok else "现有通知接口没发出去")


def _sign(secret: str, ts: int) -> str:
    digest = hmac.new(f"{ts}\n{secret}".encode(), b"", digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def feishu_post(msg: OpsMessage) -> dict[str, Any]:
    """OpsMessage → 飞书 post 富文本的 content。"""
    rows: list[list[dict[str, Any]]] = []
    for s in msg.sections:
        if s.title:
            rows.append([{"tag": "text", "text": f"【{s.title}】"}])
        for ln in s.lines:
            row: list[dict[str, Any]] = [{"tag": "text", "text": ln.text}]
            if ln.link:
                row.append({"tag": "a", "text": " 打开", "href": ln.link})
            rows.append(row)
    return {"post": {"zh_cn": {"title": msg.title, "content": rows}}}


class FeishuWebhookSender(Sender):
    name = "feishu_webhook"

    def __init__(self, url: str, secret: str = "", *, timeout: float = 5.0, transport: httpx.BaseTransport | None = None) -> None:
        self._url = url  # 不对外暴露，不打印
        self._secret = secret
        self.timeout = timeout
        self._transport = transport

    def payload(self, msg: OpsMessage) -> dict[str, Any]:
        body: dict[str, Any] = {"msg_type": "post", "content": feishu_post(msg)}
        if self._secret:
            ts = int(time.time())
            body["timestamp"], body["sign"] = str(ts), _sign(self._secret, ts)
        return body

    def send(self, msg: OpsMessage) -> SendOut:
        try:
            with httpx.Client(timeout=self.timeout, transport=self._transport) as c:
                resp = c.post(self._url, json=self.payload(msg))
            data = resp.json() if resp.content else {}
            code = data.get("code", data.get("StatusCode", 0))
            if resp.status_code == 200 and code in (0, None):
                return SendOut(sender=self.name, delivered=True)
            why = f"HTTP {resp.status_code}，飞书回 code={code} {str(data.get('msg', ''))[:80]}"
        except Exception as e:  # noqa: BLE001  网络错、JSON 错都只记类型，不记网址
            why = f"{type(e).__name__}"
        why = redact_text(why)
        log.warning("飞书运维机器人没发出去：%s", why)
        return SendOut(sender=self.name, delivered=False, detail=why)


def _redacted(msg: OpsMessage) -> OpsMessage:
    """标题和每行文字按样子脱敏（链接是后台网址，不动）。"""
    sections = [s.model_copy(update={"title": redact_text(s.title),
                                     "lines": [ln.model_copy(update={"text": redact_text(ln.text)}) for ln in s.lines]})
                for s in msg.sections]
    return msg.model_copy(update={"title": redact_text(msg.title), "sections": sections})


class FeishuAppSender(Sender):
    name = "feishu_app"

    def __init__(self, client: FeishuAppClient) -> None:
        self.client = client  # 和业务通知同一个（app.core.notify.FeishuAppNotifier.client）

    def send(self, msg: OpsMessage) -> SendOut:
        ok, why = self.client.send("post", feishu_post(_redacted(msg))["post"])
        if ok:
            return SendOut(sender=self.name, delivered=True)
        log.warning("飞书应用机器人没发出去运维消息：%s", why)
        return SendOut(sender=self.name, delivered=False, detail=why)


def read_webhook(os_: OpsSettings) -> tuple[str, str, str]:
    """（地址，签名密钥，从哪来：file / env / ""）。文件不存在或是空的算没配。只在发送层里用，结果不许打印。"""
    path: Path | None = os_.OPS_FEISHU_WEBHOOK_FILE
    if path is not None:
        try:
            lines = [x.strip() for x in Path(path).read_text(encoding="utf-8").splitlines() if x.strip()]
        except OSError:
            lines = []
        if lines and lines[0].startswith("https://"):
            return lines[0], (lines[1] if len(lines) > 1 else os_.OPS_FEISHU_SECRET.get_secret_value()), "file"
    url = os_.OPS_FEISHU_WEBHOOK.get_secret_value().strip()
    if url.startswith("https://"):
        return url, os_.OPS_FEISHU_SECRET.get_secret_value(), "env"
    return "", "", ""


def build_sender(os_: OpsSettings, notifier: Notifier, transport: httpx.BaseTransport | None = None) -> Sender:
    notifier = unwrap(notifier)  # 业务通知外面包着通知策略；运维直接用里面的发法
    kind = os_.OPS_SENDER
    url, secret, _src = read_webhook(os_)
    if kind == "log":
        return LogSender()
    if kind in ("auto", "feishu_webhook") and url:
        return FeishuWebhookSender(url, secret, transport=transport)
    if kind == "feishu_webhook":
        return LogSender()  # 点名要飞书但没配地址：只写日志，不报错
    if kind in ("auto", "feishu_app") and isinstance(notifier, FeishuAppNotifier):
        return FeishuAppSender(notifier.client)
    if kind == "feishu_app":
        return LogSender()  # 点名要应用机器人但底座没配 FEISHU_APP_FILE：只写日志
    if kind in ("auto", "core_notifier") and isinstance(notifier, FeishuNotifier):
        return CoreNotifierSender(notifier)
    if kind == "core_notifier" and not isinstance(notifier, LogNotifier):
        return CoreNotifierSender(notifier)  # 测试里的假通知器
    return LogSender()


def sender_status(os_: OpsSettings, notifier: Notifier) -> dict[str, Any]:
    """后台「飞书汇报」区显示用：只说配没配、走哪种、地址或凭证从哪读；不给地址、凭证本身。"""
    _url, secret, src = read_webhook(os_)
    s = build_sender(os_, notifier)
    notifier = unwrap(notifier)
    where = {"file": f"文件 {os_.OPS_FEISHU_WEBHOOK_FILE}", "env": "环境变量 OPS_FEISHU_WEBHOOK", "": ""}[src]
    signed = bool(secret) if src else False
    if s.name == "feishu_app":  # 凭证在底座的 FEISHU_APP_FILE 里（应用机器人没有签名这一说）
        where, signed = getattr(notifier, "source", "") or "底座 FEISHU_APP_FILE", False
    labels = {"feishu_webhook": "飞书群机器人", "feishu_app": "飞书应用机器人（私聊）", "core_notifier": "现有通知接口（底座 FEISHU_WEBHOOK）",
              "log": "没配（只写日志）"}
    return {"sender": s.name, "label": labels.get(s.name, s.name), "configured": s.configured, "source": where,
            "signed": signed, "mode": os_.OPS_SENDER}
