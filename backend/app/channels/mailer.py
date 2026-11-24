"""发信（notify.email 节点背后的实现）。没配邮件服务时整块关闭：节点回 off，「我的订单」页面不出现。

- 生产：SMTP（Python 自带 smtplib，不加依赖）。EMAIL_SMTP_HOST、EMAIL_FROM 都填了才算配了；密码只在 .env。
- 开发走查：EMAIL_DEV_DIR 指一个目录，信写成文件放那里（APP_ENV=prod 时不认）。
- 测试：app.state.email_sender 放一个假的（收到的信记在列表里）。
发件员在 channels 的 lifespan 里装上（set_sender），关掉时卸下。
"""

from __future__ import annotations

import logging
import re
import smtplib
import ssl
import threading
from collections.abc import Callable
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path

from app.core.db import utcnow

log = logging.getLogger("app.channels.mailer")

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}$")

Sender = Callable[[str, str, str], None]  # (to, subject, text)；发不出去抛异常

_LOCK = threading.Lock()
_SENDER: Sender | None = None
_LABEL = ""


def set_sender(sender: Sender | None, label: str = "") -> None:
    global _SENDER, _LABEL
    with _LOCK:
        _SENDER, _LABEL = sender, label if sender else ""


def get_sender() -> Sender | None:
    return _SENDER


def enabled() -> bool:
    return _SENDER is not None


def label() -> str:
    return _LABEL


def smtp_sender(host: str, port: int, user: str, password: str, from_addr: str, *, use_ssl: bool = True,
                from_name: str = "", timeout: float = 15.0) -> Sender:
    def send(to: str, subject: str, text: str) -> None:
        msg = EmailMessage()
        msg["From"] = formataddr((from_name, from_addr)) if from_name else from_addr
        msg["To"] = to
        msg["Subject"] = subject
        msg["Message-ID"] = make_msgid()
        msg.set_content(text)
        if use_ssl:
            with smtplib.SMTP_SSL(host, port, timeout=timeout, context=ssl.create_default_context()) as s:
                if user:
                    s.login(user, password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=timeout) as s:
                s.starttls(context=ssl.create_default_context())
                if user:
                    s.login(user, password)
                s.send_message(msg)

    return send


def dir_sender(folder: Path) -> Sender:
    """开发用：信写成文件（走查时从这里看验证码）。"""

    def send(to: str, subject: str, text: str) -> None:
        folder.mkdir(parents=True, exist_ok=True)
        name = f"{utcnow():%Y%m%d-%H%M%S-%f}.txt"
        (folder / name).write_text(f"To: {to}\nSubject: {subject}\n\n{text}\n", encoding="utf-8")
        log.info("[开发发信] %s → %s", subject, to)

    return send


def build_sender(settings: object, app_env: str) -> tuple[Sender | None, str]:
    """按配置装发件员：SMTP 配齐了用 SMTP；开发时 EMAIL_DEV_DIR 有就写文件；都没有 = 关闭。"""
    host = getattr(settings, "EMAIL_SMTP_HOST", "")
    from_addr = getattr(settings, "EMAIL_FROM", "")
    if host and from_addr:
        pwd = getattr(settings, "EMAIL_SMTP_PASSWORD")
        return smtp_sender(host, int(getattr(settings, "EMAIL_SMTP_PORT", 465)), getattr(settings, "EMAIL_SMTP_USER", ""),
                           pwd.get_secret_value() if hasattr(pwd, "get_secret_value") else str(pwd or ""), from_addr,
                           use_ssl=bool(getattr(settings, "EMAIL_SMTP_SSL", True)),
                           from_name=getattr(settings, "EMAIL_FROM_NAME", "")), "smtp"
    dev_dir = getattr(settings, "EMAIL_DEV_DIR", None)
    if dev_dir and app_env != "prod":
        return dir_sender(Path(dev_dir)), "dev-dir"
    return None, ""
