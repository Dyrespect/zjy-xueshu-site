"""渠道模块自己的配置（读同一个 .env）。企业微信的凭证（WECOM_CORPID 等）在底座 core/config.py。

微信客服要不要用，看后台「入口」页的开关（entry_config.wecom_enabled，默认关），不在这里。
「我来接」不再把微信会话转人工（主窗口裁决 K3），原来的 WECOM_SERVICER_USERID 删了。
"""

from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr

from app.core.config import ModuleSettings


class ChannelsSettings(ModuleSettings):
    # 企业微信接口地址（测试里换成假的）
    WECOM_API_BASE: str = "https://qyapi.weixin.qq.com/cgi-bin"
    # 后台发件员：每秒把「已批」的待发发出去
    CHANNELS_DISPATCH: bool = True
    # 后台圈：微信客服回调队列、客户记忆的事件消费（测试里关掉，手动调）
    CHANNELS_TICK: bool = True
    # 网页聊天单个文件上限（MB）
    WEB_UPLOAD_MAX_MB: int = 50

    # ---- 发邮件（可选：「我的订单」的验证码、发票通知；没配 = 整块关闭）----
    EMAIL_SMTP_HOST: str = ""
    EMAIL_SMTP_PORT: int = 465
    EMAIL_SMTP_USER: str = ""
    EMAIL_SMTP_PASSWORD: SecretStr = SecretStr("")
    EMAIL_SMTP_SSL: bool = True  # true：SMTP_SSL（465）；false：STARTTLS（587）
    EMAIL_FROM: str = ""
    EMAIL_FROM_NAME: str = "心理学汇报 PPT 定制"
    EMAIL_DEV_DIR: Path | None = None  # 开发走查：信写成文件放这里（APP_ENV=prod 时不认）

    # ---- 登录（docs/任务单/12_登录与正规化_设计.md）----
    # 微信登录（微信里静默授权 + 电脑扫服务号带参二维码）。AppID、AppSecret 跟付款共用同两个配置（官方要求 openid 和下单用同一个
    # appid；不另设，免得两处填得不一样）：WECHATPAY_APPID、WECHAT_MP_APPSECRET_FILE（优先）/ WECHAT_MP_APPSECRET。
    WECHAT_LOGIN_ENABLED: bool = True
    WECHATPAY_APPID: str = ""
    WECHAT_MP_APPSECRET_FILE: Path | None = None
    WECHAT_MP_APPSECRET: SecretStr = SecretStr("")
    # 服务号「消息与事件推送」的 Token、EncodingAESKey（scripts/mp_push_secrets.py 随机生成写进文件，Edison 照着填进开发者平台）。
    # Token 没配 = 电脑扫码登录不出现（退回手机号）；EncodingAESKey 没配 = 只认明文模式（不建议）
    WECHAT_MP_TOKEN_FILE: Path | None = None
    WECHAT_MP_TOKEN: SecretStr = SecretStr("")
    WECHAT_MP_AES_KEY_FILE: Path | None = None
    WECHAT_MP_AES_KEY: SecretStr = SecretStr("")
    WECHAT_MP_API_BASE: str = "https://api.weixin.qq.com"
    # 本机走查用假微信（不连微信：静默授权直接回调、扫码有「模拟扫码」）。APP_ENV=prod 时不认
    WECHAT_MP_FAKE: bool = False

    # 短信验证码（腾讯云短信，官方 SDK tencentcloud-sdk-python-sms）：四样齐了才开，缺一样整块关（接口 404、页面上不出现）
    SMS_SECRET_FILE: Path | None = None  # 两行：第一行 SecretId，第二行 SecretKey（子账号，只给短信权限）
    SMS_SDK_APP_ID: str = ""
    SMS_SIGN_NAME: str = ""  # 签名内容（不是签名 ID），如「竹涧云科技」；模板正文里不写签名
    SMS_TEMPLATE_ID: str = ""  # 验证码模板：{1}为您的登录验证码，请于{2}分钟内填写，如非本人操作，请忽略本短信。
    SMS_REGION: str = "ap-guangzhou"
    SMS_CODE_TTL_MIN: int = 5
    SMS_PHONE_DAILY: int = 5  # 同一手机号每天最多几条（腾讯云默认一个自然日 2 条，控制台要改到不低于这个数）
    SMS_IP_HOURLY: int = 10  # 同一 IP 每小时最多几条
    SMS_DAILY_TOTAL: int = 300  # 全站每天最多几条（被刷时最多亏这么多）
    # 本机走查用假短信：码写成文件放 SMS_DEV_DIR（不发真短信）。APP_ENV=prod 时不认
    SMS_FAKE: bool = False
    SMS_DEV_DIR: Path | None = None

    def mp_appsecret(self) -> str:
        return _first_line(self.WECHAT_MP_APPSECRET_FILE) if self.WECHAT_MP_APPSECRET_FILE else \
            self.WECHAT_MP_APPSECRET.get_secret_value().strip()

    def mp_token(self) -> str:
        return _first_line(self.WECHAT_MP_TOKEN_FILE) if self.WECHAT_MP_TOKEN_FILE else self.WECHAT_MP_TOKEN.get_secret_value().strip()

    def mp_aes_key(self) -> str:
        return _first_line(self.WECHAT_MP_AES_KEY_FILE) if self.WECHAT_MP_AES_KEY_FILE else \
            self.WECHAT_MP_AES_KEY.get_secret_value().strip()

    def sms_secret(self) -> tuple[str, str]:
        """（SecretId, SecretKey）；文件没配或读不到 = 两个空串。只在发短信那一下读，不缓存、不打印。"""
        if self.SMS_SECRET_FILE is None:
            return "", ""
        try:
            lines = [x.strip() for x in Path(self.SMS_SECRET_FILE).read_text(encoding="utf-8").splitlines() if x.strip()]
        except OSError:
            return "", ""
        return (lines[0], lines[1]) if len(lines) >= 2 else ("", "")


def _first_line(path: Path | None) -> str:
    if path is None:
        return ""
    try:
        first = Path(path).read_text(encoding="utf-8").strip().splitlines()
    except OSError:
        return ""
    return first[0].strip() if first else ""
