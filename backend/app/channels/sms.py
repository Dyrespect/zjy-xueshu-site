"""短信验证码（登录、绑手机号；docs/任务单/12_登录与正规化_设计.md 第八节）。

- 网关：腾讯云短信（官方 SDK tencentcloud-sdk-python-sms，用到时才 import）；测试用假网关（记在列表里），本机走查写成文件。
  四样配置（SMS_SECRET_FILE、SMS_SDK_APP_ID、SMS_SIGN_NAME、SMS_TEMPLATE_ID）缺一样 = 整块关：接口 404、页面上不出现。
- 发：只有 send_code 能调网关（scripts/check.py 规矩 23 第 2 条）；发之前依次过四道限流（core.ratelimit，多进程共用）：
  同一手机号 60 秒 1 条、同一手机号每天 SMS_PHONE_DAILY 条、同一 IP 每小时 SMS_IP_HOURLY 条、全站每天 SMS_DAILY_TOTAL 条。
- 码：6 位数字；库里只存 HMAC；5 分钟有效、错 5 次作废、用过作废；同一个号新发一条，旧的作废。
- 模板（官方正文模板审核标准的正确示例，一字不改）：{1}为您的登录验证码，请于{2}分钟内填写，如非本人操作，请忽略本短信。
  {1} = 验证码，{2} = 分钟数；签名（SMS_SIGN_NAME）由腾讯云加在前面，正文不写签名（官方：正文「不支持【】」）。
- 日志、事件里手机号只放打码的（mask_phone），验证码一律不放（规矩 23 第 1 条）。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol

from fastapi import HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.channels import limits
from app.channels.login import mask_phone
from app.channels.models import SmsCode
from app.channels.settings import ChannelsSettings
from app.core import access
from app.core.db import utcnow
from app.core.events import record_event

Purpose = Literal["login", "bind"]
MAX_ATTEMPTS = 5
VERIFY_PER_HOUR = 20
# 腾讯云回的错误码 → 给客人看的话（发送短信接口文档的错误码一节）
_LIMIT_PREFIX = "LimitExceeded."
_ALERT_CODES = ("FailedOperation.InsufficientBalanceInSmsPackage", "FailedOperation.SignatureIncorrectOrUnapproved",
                "FailedOperation.TemplateIncorrectOrUnapproved", "UnauthorizedOperation.")


@dataclass
class SmsResult:
    ok: bool
    error_code: str = ""  # 腾讯云的错误码（Ok 以外的），不是验证码
    request_id: str = ""


class SmsSender(Protocol):
    label: str

    def send(self, phone: str, params: list[str]) -> SmsResult: ...


class TencentSms:
    """腾讯云短信 SendSms（https://cloud.tencent.com/document/api/382/55981）：PhoneNumberSet 用 E.164，SignName 填签名内容，
    TemplateParamSet 个数和模板变量一致；回包 SendStatusSet[0].Code == "Ok" 才算发出去。"""

    label = "tencent"

    def __init__(self, s: ChannelsSettings) -> None:
        self.s = s

    def send(self, phone: str, params: list[str]) -> SmsResult:
        from tencentcloud.common import credential
        from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
        from tencentcloud.common.profile.client_profile import ClientProfile
        from tencentcloud.common.profile.http_profile import HttpProfile
        from tencentcloud.sms.v20210111 import models, sms_client

        sid, skey = self.s.sms_secret()
        if not sid or not skey:
            return SmsResult(False, "LocalConfig.SecretMissing")
        hp = HttpProfile()
        hp.endpoint = "sms.tencentcloudapi.com"
        hp.reqTimeout = 10
        cp = ClientProfile()
        cp.httpProfile = hp
        req = models.SendSmsRequest()
        req.PhoneNumberSet = [phone]
        req.SmsSdkAppId = self.s.SMS_SDK_APP_ID
        req.SignName = self.s.SMS_SIGN_NAME
        req.TemplateId = self.s.SMS_TEMPLATE_ID
        req.TemplateParamSet = params
        try:
            resp = sms_client.SmsClient(credential.Credential(sid, skey), self.s.SMS_REGION, cp).SendSms(req)
        except TencentCloudSDKException as e:  # 只取错误码，异常文字不往外带
            return SmsResult(False, str(e.get_code() or "SDKError")[:80], str(e.get_request_id() or "")[:64])
        except Exception as e:  # noqa: BLE001  网络之类：只记类名
            return SmsResult(False, f"Network.{type(e).__name__}"[:80])
        st = (resp.SendStatusSet or [None])[0]
        if st is None:
            return SmsResult(False, "EmptyResponse", str(resp.RequestId or ""))
        return SmsResult(st.Code == "Ok", "" if st.Code == "Ok" else str(st.Code)[:80], str(resp.RequestId or ""))


class FakeSms:
    """假网关：测试里记在 sent 列表；本机走查（SMS_FAKE + SMS_DEV_DIR）把每条写成一个文件。不发真短信。"""

    label = "fake"

    def __init__(self, dev_dir: Path | None = None, fail_code: str = "") -> None:
        self.sent: list[dict[str, Any]] = []
        self.dev_dir = dev_dir
        self.fail_code = fail_code

    def send(self, phone: str, params: list[str]) -> SmsResult:
        if self.fail_code:
            return SmsResult(False, self.fail_code)
        self.sent.append({"phone": phone, "params": list(params)})
        if self.dev_dir is not None:
            self.dev_dir.mkdir(parents=True, exist_ok=True)
            name = f"{utcnow().strftime('%Y%m%d-%H%M%S-%f')}-{phone[-4:]}.txt"
            (self.dev_dir / name).write_text(f"To: {phone}\n{params[0]}为您的登录验证码，请于{params[1]}分钟内填写。\n",
                                             encoding="utf-8")
        return SmsResult(True)

    def last_code(self, phone: str | None = None) -> str:
        rows = [x for x in self.sent if phone is None or x["phone"] == phone]
        return rows[-1]["params"][0]


def configured(s: ChannelsSettings) -> bool:
    return bool(s.SMS_SECRET_FILE and s.SMS_SDK_APP_ID and s.SMS_SIGN_NAME and s.SMS_TEMPLATE_ID)


def build_sender(s: ChannelsSettings, app_env: str) -> SmsSender | None:
    if s.SMS_FAKE and app_env != "prod":
        return FakeSms(s.SMS_DEV_DIR)
    return TencentSms(s) if configured(s) else None


def sender_of(request: Request) -> SmsSender | None:
    """测试和本机放在 app.state.sms_sender（channels 的 lifespan 按配置建好）；None = 短信整块关。"""
    return getattr(request.app.state, "sms_sender", None)


def enabled(request: Request) -> bool:
    return sender_of(request) is not None


def require_on(request: Request) -> SmsSender:
    s = sender_of(request)
    if s is None:
        raise HTTPException(404, detail="Not Found")
    return s


# ---------------------------------------------------------------- 发、核

def _mac(request: Request, purpose: str, phone: str, sms_code: str) -> str:
    return hmac.new(access._secret(request).encode(), f"{purpose}|{phone}|{sms_code}".encode(), hashlib.sha256).hexdigest()


def _settings(request: Request) -> ChannelsSettings:
    from app.channels.runtime import get_channels

    return get_channels(request.app).settings


def send_code(request: Request, db: Session, phone: str, purpose: Purpose, ip: str, *, alert: Any = None) -> datetime:
    """发一条验证码。先过四道限流（规矩 23 第 2 条），再作废旧码、存 HMAC、调网关。返回过期时间。不成功抛 HTTPException。"""
    sender = require_on(request)
    s = _settings(request)
    lim = limits.limiter(request.app)
    if not lim.hit("sms.phone_60s", phone, limit=1, window=60):
        raise HTTPException(429, detail="验证码 60 秒内只能发一条，稍等一下再点")
    if not lim.hit("sms.phone_daily", phone, limit=max(1, s.SMS_PHONE_DAILY), window=86400):
        raise HTTPException(429, detail="这个手机号今天收的验证码太多了，明天再试；急的话用微信登录")
    if not lim.hit("sms.ip_hourly", ip or "-", limit=max(1, s.SMS_IP_HOURLY), window=3600):
        raise HTTPException(429, detail="发得太频繁了，过一会儿再试")
    if not lim.hit("sms.daily_total", "all", limit=max(1, s.SMS_DAILY_TOTAL), window=86400):
        _alert(request, alert, "sms.daily_total", f"今天的短信验证码到上限了（SMS_DAILY_TOTAL={s.SMS_DAILY_TOTAL}），可能有人在刷，去后台看看")
        raise HTTPException(503, detail="验证码暂时发不出去，先用微信登录，或者过一会儿再试")
    ttl = max(1, s.SMS_CODE_TTL_MIN)
    now = utcnow()
    sms_code = f"{secrets.randbelow(1_000_000):06d}"
    db.execute(update(SmsCode).where(SmsCode.phone == phone, SmsCode.purpose == purpose, SmsCode.used_at.is_(None))
               .values(used_at=now))
    res = sender.send(phone, [sms_code, str(ttl)])
    if not res.ok:
        record_event(db, "customer.sms_failed", "", {"phone": mask_phone(phone), "error": res.error_code, "purpose": purpose})
        db.commit()
        if res.error_code.startswith(_LIMIT_PREFIX):
            raise HTTPException(429, detail="这个手机号收短信太频繁了（运营商限制），过一会儿再试")
        if res.error_code.startswith("InvalidParameterValue.IncorrectPhoneNumber"):
            raise HTTPException(400, detail="手机号不对，只支持中国大陆手机号")
        if res.error_code.startswith(_ALERT_CODES) or res.error_code.startswith("LocalConfig."):
            _alert(request, alert, f"sms.{res.error_code}", f"短信验证码发不出去：腾讯云回 {res.error_code}（签名、模板、余额或密钥），去腾讯云短信控制台看看")
        raise HTTPException(503, detail="验证码暂时发不出去，过一会儿再试")
    db.add(SmsCode(phone=phone, purpose=purpose, code_mac=_mac(request, purpose, phone, sms_code), ip=(ip or "")[:64],
                   attempts=0, created_at=now, expires_at=now + timedelta(minutes=ttl)))
    record_event(db, "customer.sms_sent", "", {"phone": mask_phone(phone), "purpose": purpose, "via": sender.label})
    return now + timedelta(minutes=ttl)


def check_code(request: Request, db: Session, phone: str, purpose: Purpose, sms_code: str) -> None:
    """核验证码：5 分钟、错 5 次作废、用过作废。对了把这条标成用过（调用方提交）；不对提交试错次数后抛 HTTPException。"""
    require_on(request)
    if not limits.limiter(request.app).hit("sms.verify", phone, limit=VERIFY_PER_HOUR, window=3600):
        raise HTTPException(429, detail="试得太多了，一小时后再来")
    row = db.scalar(select(SmsCode).where(SmsCode.phone == phone, SmsCode.purpose == purpose)
                    .order_by(SmsCode.id.desc()).limit(1))
    now = utcnow()
    if row is None or row.used_at is not None:
        raise HTTPException(400, detail="先点「获取验证码」")
    if row.expires_at <= now:
        raise HTTPException(400, detail="验证码过期了，重新获取一个")
    if row.attempts >= MAX_ATTEMPTS:
        raise HTTPException(400, detail="错的次数太多，这个验证码作废了，重新获取一个")
    given = "".join(ch for ch in (sms_code or "") if ch.isdigit())
    if not hmac.compare_digest(row.code_mac, _mac(request, purpose, phone, given)):
        row.attempts += 1
        left = MAX_ATTEMPTS - row.attempts
        db.commit()
        raise HTTPException(400, detail=f"验证码不对，还能试 {left} 次" if left > 0 else "错的次数太多，这个验证码作废了，重新获取一个")
    row.used_at = now


def _alert(request: Request, alert: Any, key: str, text: str) -> None:
    """配置类错误告诉负责人一声（同一种一小时一次）。"""
    if alert is None or not limits.limiter(request.app).hit("sms.alert", key, limit=1, window=3600):
        return
    try:
        alert.send(text)
    except Exception:  # noqa: BLE001  告警发不出去不影响客人
        pass


def prune(db: Session, now: datetime | None = None) -> int:
    """验证码留一天就删（只是 HMAC，也不多留）。"""
    from sqlalchemy import delete

    cut = (now or utcnow()) - timedelta(days=1)
    return db.execute(delete(SmsCode).where(SmsCode.created_at < cut)).rowcount or 0
