"""短信验证码（12 号设计第八节）：没配整块关、四道限流、5 分钟过期、错 5 次作废、用过作废、库里不存明文、事件里打码、
腾讯云请求按官方字段拼（假的 SmsClient，不联网、不发真短信）。"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from sqlalchemy import select

from app.channels.models import SmsCode
from app.channels.settings import ChannelsSettings
from app.channels.sms import FakeSms, TencentSms
from app.core.db import utcnow
from app.core.events import list_events
from app.intake.runtime import get_runtime
from tests.channels.login_helpers import MOBILE_UA, PC_UA, all_rows_text, client, login_app

PHONE = "13800138000"


def _start(c, phone: str = PHONE, purpose: str = "login"):
    return c.post("/api/channels/login/sms/start", json={"phone": phone, "purpose": purpose})


def _verify(c, code: str, phone: str = PHONE, purpose: str = "login"):
    return c.post("/api/channels/login/sms/verify", json={"phone": phone, "purpose": purpose, "code": code})


def _clear(app, bucket: str, key: str, limit: int, window: int) -> None:
    app.state.ratelimit.clear(bucket, key, limit=limit, window=window)


def test_sms_off_hides_everything(settings, notifier, tmp_path):
    """四样配置缺一样：接口 404、会话里 sms=false、登录方式里没有手机号。"""
    app = login_app(settings, notifier, tmp_path, wx=False, qr=False, sms=None)
    with client(app, MOBILE_UA) as c:
        s = c.get("/api/channels/account/session").json()
        assert s["sms"] is False and "sms" not in s["methods"]
        assert _start(c).status_code == 404 and _verify(c, "123456").status_code == 404
    from app.channels import sms as sms_mod

    assert sms_mod.configured(ChannelsSettings(_env_file=None)) is False
    assert sms_mod.configured(ChannelsSettings(_env_file=None, SMS_SECRET_FILE=tmp_path / "k", SMS_SDK_APP_ID="1400",
                                               SMS_SIGN_NAME="竹涧云科技", SMS_TEMPLATE_ID="")) is False
    assert sms_mod.build_sender(ChannelsSettings(_env_file=None, SMS_FAKE=True), "prod") is None  # 生产不认假网关


def test_sms_login_happy_path_and_storage(settings, notifier, tmp_path):
    fake = FakeSms()
    app = login_app(settings, notifier, tmp_path, sms=fake)
    with client(app, MOBILE_UA) as c:
        r = _start(c, "+86 138-0013-8000")
        assert r.status_code == 200 and r.json()["masked"] == "138****8000" and r.json()["ttl_min"] == 5
        assert fake.sent[-1]["phone"] == "+8613800138000" and fake.sent[-1]["params"][1] == "5"
        code = fake.last_code()
        assert len(code) == 6 and code.isdigit()
        ok = _verify(c, code)
        assert ok.status_code == 200 and "psy_sess" in ok.cookies
        s = c.get("/api/channels/account/session").json()
        assert s["method"] == "sms" and s["label"] == "手机 138****8000" and s["phone_bound"]
        assert _verify(c, code).status_code == 400  # 用过作废
    text = all_rows_text(get_runtime(app).database)
    assert f"'{code}'" not in text and f" {code}," not in text  # 库里没有验证码明文（只有 HMAC）
    with get_runtime(app).database.session(write=False) as db:
        evs = list_events(db, limit=200)
        assert all("13800138000" not in str(e.content) and code not in str(e.content) for e in evs)
        assert any(e.type == "customer.sms_sent" and e.content.get("phone") == "138****8000" for e in evs)
    assert _start(client(app, MOBILE_UA), "1234567890").status_code == 400  # 不是大陆手机号


def test_sms_rate_limits(settings, notifier, tmp_path):
    """同一手机号 60 秒 1 条；同一手机号每天上限；同一 IP 每小时上限；全站每天上限（到了告诉负责人）。"""
    fake = FakeSms()
    app = login_app(settings, notifier, tmp_path, sms=fake, SMS_PHONE_DAILY=3, SMS_IP_HOURLY=4, SMS_DAILY_TOTAL=6)
    e164 = "+8613800138000"
    with client(app, MOBILE_UA) as c:
        assert _start(c).status_code == 200
        r = _start(c)
        assert r.status_code == 429 and "60 秒" in r.json()["detail"]
        for _ in range(2):
            _clear(app, "sms.phone_60s", e164, 1, 60)
            assert _start(c).status_code == 200
        _clear(app, "sms.phone_60s", e164, 1, 60)
        r = _start(c)
        assert r.status_code == 429 and "今天" in r.json()["detail"]  # 每天 3 条
        assert len(fake.sent) == 3
        # 同一 IP 每小时 4 条（上面过了 IP 那一道的是 3 次：被 60 秒、每天拦下的走不到 IP 这道）
        assert _start(c, "13900000001").status_code == 200
        r = _start(c, "13900000002")
        assert r.status_code == 429 and "频繁" in r.json()["detail"]
        # 全站每天 6 条：换 IP 桶清掉，再发两个号就到顶
        app.state.ratelimit.clear("sms.ip_hourly", "testclient", limit=4, window=3600)
        assert _start(c, "13900000003").status_code == 200
        assert _start(c, "13900000004").status_code == 200
        r = _start(c, "13900000005")
        assert r.status_code == 503
        assert any("上限" in m for m in notifier.sent)


def test_sms_code_expiry_and_attempts(settings, notifier, tmp_path):
    """5 分钟过期；错 5 次作废（第 5 次之后对的也不认）；新发一条旧的作废。"""
    fake = FakeSms()
    app = login_app(settings, notifier, tmp_path, sms=fake)
    e164 = "+8613800138000"
    with client(app, MOBILE_UA) as c:
        _start(c)
        code = fake.last_code()
        for i in range(4):
            r = _verify(c, "000000" if code != "000000" else "111111")
            assert r.status_code == 400 and f"还能试 {4 - i} 次" in r.json()["detail"]
        r = _verify(c, "000000" if code != "000000" else "111111")
        assert "作废" in r.json()["detail"]
        assert "作废" in _verify(c, code).json()["detail"]
        # 过期
        _clear(app, "sms.phone_60s", e164, 1, 60)
        _start(c)
        code2 = fake.last_code()
        with get_runtime(app).database.session() as db:
            row = db.scalar(select(SmsCode).order_by(SmsCode.id.desc()).limit(1))
            row.expires_at = utcnow() - timedelta(seconds=1)
        assert "过期" in _verify(c, code2).json()["detail"]
        # 新发一条，旧的作废
        _clear(app, "sms.phone_60s", e164, 1, 60)
        _start(c)
        old = fake.last_code()
        _clear(app, "sms.phone_60s", e164, 1, 60)
        _start(c)
        new = fake.last_code()
        if old != new:
            assert _verify(c, old).status_code == 400
        assert _verify(c, new).status_code == 200


def test_sms_gateway_errors_mapped(settings, notifier, tmp_path):
    """腾讯云回错误码：频率类 429、号码不对 400、签名 / 模板 / 余额 503 + 告诉负责人；验证码不落库。"""
    for fail, status in (("LimitExceeded.PhoneNumberDailyLimit", 429), ("InvalidParameterValue.IncorrectPhoneNumber", 400),
                         ("FailedOperation.SignatureIncorrectOrUnapproved", 503)):
        notifier.sent.clear()
        app = login_app(settings, notifier, tmp_path / fail, sms=FakeSms(fail_code=fail))
        with client(app, PC_UA) as c:
            app.state.ratelimit.clear("sms.phone_60s", "+8613800138000", limit=1, window=60)
            assert _start(c).status_code == status
        if status == 503:
            assert any("SignatureIncorrectOrUnapproved" in m for m in notifier.sent)


def test_tencent_request_fields(tmp_path, monkeypatch):
    """TencentSms 按 SendSms 文档拼：E.164 号码、SdkAppId、签名内容、模板 ID、两个参数；Code=Ok 才算发出去。"""
    seen: dict = {}

    class FakeClient:
        def __init__(self, cred, region, profile):
            seen.update(sid=cred.secretId, region=region, endpoint=profile.httpProfile.endpoint)

        def SendSms(self, req):  # noqa: N802  照 SDK 的名字
            seen.update(phones=req.PhoneNumberSet, app=req.SmsSdkAppId, sign=req.SignName, tpl=req.TemplateId,
                        params=req.TemplateParamSet)
            return SimpleNamespace(RequestId="R1", SendStatusSet=[SimpleNamespace(Code=seen.get("code", "Ok"))])

    from tencentcloud.sms.v20210111 import sms_client

    monkeypatch.setattr(sms_client, "SmsClient", FakeClient)
    key = tmp_path / "sms_secret"
    key.write_text("AKIDtestid\nsecretkey\n", encoding="utf-8")
    s = ChannelsSettings(_env_file=None, SMS_SECRET_FILE=key, SMS_SDK_APP_ID="1400000001", SMS_SIGN_NAME="竹涧云科技",
                         SMS_TEMPLATE_ID="2000001")
    assert TencentSms(s).send("+8613800138000", ["123456", "5"]).ok
    assert seen == {"sid": "AKIDtestid", "region": "ap-guangzhou", "endpoint": "sms.tencentcloudapi.com",
                    "phones": ["+8613800138000"], "app": "1400000001", "sign": "竹涧云科技", "tpl": "2000001", "params": ["123456", "5"]}
    seen["code"] = "LimitExceeded.PhoneNumberThirtySecondLimit"
    r = TencentSms(s).send("+8613800138000", ["123456", "5"])
    assert not r.ok and r.error_code == "LimitExceeded.PhoneNumberThirtySecondLimit"
