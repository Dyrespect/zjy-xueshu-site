"""渠道自己的表。消息、会话、订单都在订单中枢（intake）的表里，这里只放入口模块（D）自己的：

- channels_wecom_cursor：微信客服拉消息的游标（断点续拉）。
- channels_wecom_inbox：微信客服回调队列（回调只验签、解密、写一行、回 success；工人消费）。
- channels_people：客户（同一个人）。网页、微信两个会话用同一枚激活码合成一个人；偏好按事实记在这里。
- channels_memory_cursor：customer.memory 消费事件表的游标。
- channels_contacts：可选的「我的订单」——这个人验证过的邮箱（验证码和登录令牌用 itsdangerous 签名，不建表）。
登录（docs/任务单/12_登录与正规化_设计.md 第五节）：账号就是 channels_people，不另造用户体系。
- channels_logins：登录身份（服务号 openid、手机号）；一个微信、一个手机号只属于一个人。
- channels_sms_codes：短信验证码（只存 HMAC，不存明文；5 分钟、错 5 次作废、用过作废）。
- channels_qr_logins：电脑扫码登录票（场景值、浏览器凭证的 HMAC、扫到的人）。
- channels_mp_tokens：服务号 access_token 全局一份（稳定版接口，集中缓存）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, UTCDateTime, utcnow


class WecomCursor(Base):
    __tablename__ = "channels_wecom_cursor"

    open_kfid: Mapped[str] = mapped_column(String(64), primary_key=True)
    cursor: Mapped[str] = mapped_column(String(128), default="")
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class WecomInbox(Base):
    """回调来一次写一行（回调里只有 Token 和 OpenKfId，消息正文要拿 Token 去拉）。"""

    __tablename__ = "channels_wecom_inbox"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    open_kfid: Mapped[str] = mapped_column(String(64), default="")
    token: Mapped[str] = mapped_column(String(256), default="")  # 10 分钟有效；过了 9 分钟就不带 token 拉
    received_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)  # pending | done | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    run_after: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    error: Mapped[str] = mapped_column(String(512), default="")
    done_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class Person(Base):
    """一个客户（人）。会话表 intake_customers.person_id 指这里（经 orders.set_customer_memory 写）。"""

    __tablename__ = "channels_people"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    preferences: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    merged_into_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)  # 被并走的留痕
    # 登录（12 号设计第五节）：会话代数（「所有设备都退出」+1，旧 cookie 全失效）；上次点「先不绑手机号」的时间
    session_epoch: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    phone_prompt_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class MemoryCursor(Base):
    __tablename__ = "channels_memory_cursor"

    name: Mapped[str] = mapped_column(String(32), primary_key=True)
    last_event_id: Mapped[int] = mapped_column(Integer, default=0)


class Contact(Base):
    """这个人验证过的邮箱（「我的订单」凭订单号 + 这个邮箱查）。"""

    __tablename__ = "channels_contacts"
    __table_args__ = (UniqueConstraint("person_id", "email"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    person_id: Mapped[int] = mapped_column(Integer, index=True)
    email: Mapped[str] = mapped_column(String(120), index=True)  # 小写
    verified_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)


class Login(Base):
    """登录身份：kind = wx（服务号下的 openid）/ phone（手机号，E.164，如 +8613812345678）。（kind, value）唯一。
    openid、手机号都不进日志和事件（scripts/check.py 规矩 22、23）；页面上手机号一律打码。"""

    __tablename__ = "channels_logins"
    __table_args__ = (UniqueConstraint("kind", "value"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    person_id: Mapped[int] = mapped_column(Integer, index=True)
    kind: Mapped[str] = mapped_column(String(8))
    value: Mapped[str] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class SmsCode(Base):
    """发出去的一条验证码。code_mac = HMAC(SESSION_SECRET, 用途|手机号|码)，库里没有明文。"""

    __tablename__ = "channels_sms_codes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phone: Mapped[str] = mapped_column(String(20), index=True)
    purpose: Mapped[str] = mapped_column(String(8))  # login | bind
    code_mac: Mapped[str] = mapped_column(String(64))
    ip: Mapped[str] = mapped_column(String(64), default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    used_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class QrLogin(Base):
    """电脑扫码登录票：scene 是二维码里的场景值（L + 24 位随机），browser_mac 是只有发起的那个浏览器有的 cookie 的 HMAC。"""

    __tablename__ = "channels_qr_logins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scene: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    browser_mac: Mapped[str] = mapped_column(String(64))
    ticket: Mapped[str] = mapped_column(String(255), default="")
    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending | scanned | done
    person_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ip: Mapped[str] = mapped_column(String(64), default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow, index=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    scanned_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    done_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class MpToken(Base):
    """服务号 access_token：全局一份（官方：存储至少留 512 字符）。还剩 5 分钟以上直接用，不够加锁后用稳定版接口重拿。"""

    __tablename__ = "channels_mp_tokens"

    appid: Mapped[str] = mapped_column(String(64), primary_key=True)
    token: Mapped[str] = mapped_column(String(1024), default="")
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=utcnow)
