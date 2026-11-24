"""notify.email 发邮件。"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.channels import mailer
from app.channels.mailer import EMAIL_RE
from app.core.events import record_event
from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register


class EmailIn(BaseModel):
    to: str = Field(max_length=120)
    subject: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=20000)

    @field_validator("to")
    @classmethod
    def _addr(cls, v: str) -> str:
        v = v.strip()
        if not EMAIL_RE.match(v):
            raise ValueError("邮箱格式不对")
        return v


class EmailOut(BaseModel):
    sent: bool
    detail: str = ""


def _mask(addr: str) -> str:
    name, _, host = addr.partition("@")
    return f"{name[:2]}***@{host}"


def handler(call: NodeCall, data: EmailIn) -> NodeResult:
    sender = mailer.get_sender()
    if sender is None:
        return NodeResult(exit="off", output=EmailOut(sent=False, detail="没配邮件服务"), detail="没配邮件服务")
    try:
        sender(data.to, data.subject, data.text)
    except Exception as e:  # 发不出去不打断业务：调用方自己决定进待发还是报错
        detail = f"{type(e).__name__}: {e}"[:300]
        if call.db is not None:
            record_event(call.db, "notify.email_failed", "", {"to": _mask(data.to), "subject": data.subject[:80], "error": detail})
        return NodeResult(exit="failed", output=EmailOut(sent=False, detail=detail), detail=detail)
    if call.db is not None:
        record_event(call.db, "notify.email_sent", "", {"to": _mask(data.to), "subject": data.subject[:80], "by": call.by})
    return NodeResult(exit="sent", output=EmailOut(sent=True))


CARD = NodeCard(
    id="notify.email",
    name="发邮件",
    description="给客人发一封邮件（「我的订单」的验证码、发票通知……）。没配邮件服务时回 off，用到它的功能整块关闭或进待发。",
    category="运营",
    tech=["Python 自带 smtplib（SMTP_SSL / STARTTLS），不加依赖", "开发走查：EMAIL_DEV_DIR 写成文件",
          "发件员在 channels 的 lifespan 里装上（app/channels/mailer.py）"],
    input_model=EmailIn,
    output_model=EmailOut,
    exits=[NodeExit(key="sent", label="发出去了", kind="ok"),
           NodeExit(key="off", label="没配邮件服务", kind="fail"),
           NodeExit(key="failed", label="发信服务报错", kind="fail")],
    config=[".env：EMAIL_SMTP_HOST、EMAIL_SMTP_PORT、EMAIL_SMTP_USER、EMAIL_SMTP_PASSWORD、EMAIL_SMTP_SSL、EMAIL_FROM、EMAIL_FROM_NAME",
            ".env：EMAIL_DEV_DIR（只在开发时认）"],
    emits=["notify.email_sent", "notify.email_failed"],
    listens=["无"],
    replaceable=["以后换云邮件（阿里云、腾讯云邮件推送）：换 mailer.py 里的发件员，节点不变"],
    failure="不重试（验证码让客人再点一次；发票通知由 invoice.notify 进待发）；事件里邮箱打码，不记正文。",
    owner="D",
    status="要新做",
)
register(CARD, handler)
