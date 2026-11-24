"""自有渠道和支付的配置（读同一个 .env；测试里在 app.state.shop_settings 放一份 _env_file=None 的）。

商户号、密钥只在 .env；这里只有名字和默认值。价格不在这里（在订单中枢的设置里，走 sku.quote）。
自动确认几天也不在这里：读订单中枢设置的 auto_confirm_days（sku.catalog 给）。
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import SecretStr

from app.core.config import ModuleSettings

# 付款方式（method）→ 哪种场景能用：pc 电脑、mobile 手机浏览器、wechat 微信里
METHOD_UA: dict[str, tuple[str, ...]] = {
    "wechat_native": ("pc",),  # 二维码不能长按识别、相册识别：只给电脑（设计第五节第 3 条）
    "wechat_jsapi": ("wechat",),
    "wechat_h5": ("mobile",),
    "alipay_page": ("pc",),
    "alipay_wap": ("mobile",),  # 微信里会被拦，不出（设计第五节第 3 条）
}
METHOD_LABELS: dict[str, str] = {
    "wechat_native": "微信扫码",
    "wechat_jsapi": "微信支付",
    "wechat_h5": "微信支付",
    "alipay_page": "支付宝",
    "alipay_wap": "支付宝",
}


class ShopSettings(ModuleSettings):
    # 总开关：false 时下单页显示「暂停接单」，不建待付款单
    SHOP_ENABLED: bool = True
    # 开着的付款方式和对应节点，逗号分隔：wechat_native=pay.wechat,alipay_page=pay.alipay,alipay_wap=pay.alipay
    # 空 = 一种都没开（下单页能看价，不能付）。本机走查用 pay.fake
    SHOP_METHODS: str = ""
    # 假网关（只在测试和本机为真）。APP_ENV=prod 时为真，服务拒绝启动
    SHOP_FAKE_PAY: bool = False
    # 假网关给通知签名用的钥匙；空 = 每次启动随机
    SHOP_FAKE_SECRET: SecretStr = SecretStr("")
    # 待付款单多久过期（分钟）、同一 IP 每小时最多下几单、付款页轮询时最快几秒去网关查一次单
    SHOP_CHECKOUT_TTL_MIN: int = 30
    SHOP_IP_HOURLY_LIMIT: int = 20
    SHOP_QUERY_MIN_INTERVAL_SEC: float = 4.0
    # 定时任务（超时自动确认、关过期单、查退款）：开不开、几秒跑一次
    SHOP_TIMER_ENABLED: bool = True
    SHOP_TIMER_INTERVAL_SEC: int = 600
    # 哪些渠道的单交了水印版超时自动确认（还要订单中枢的确认来源表认 auto 才算）
    SHOP_AUTO_CONFIRM_PLATFORMS: str = "web,fk,manual"
    # 自动确认前几小时提醒客人一次（模块 E 的 deliver.preview action=remind 发）；0 = 不提醒。
    # 订单中枢设置里也有 delivery.remind_before_hours（24），本模块读不到设置，先在这里放同一个数（汇报里写了，等合一）
    SHOP_AUTO_CONFIRM_REMIND_HOURS: int = 24
    # 付完以后「去交码」按钮的地址：{code} 换成激活码。默认去兑换页（模块 D，/c/{code}；会带上这个浏览器的聊天，认领到同一个对话里）
    SHOP_REDEEM_URL: str = "/c/{code}"
    # 价目、交付说明、退款页在哪（psyppt 官网）
    SHOP_SITE_URL: str = "https://psyppt.pilipala.zj.cn"
    # 付款时显示的商品名前缀
    SHOP_SUBJECT: str = "心理学汇报 PPT 定制"

    # ---- 微信支付 APIv3（竹涧云的商户号；值只在 .env）----
    WECHATPAY_MCHID: str = ""
    WECHATPAY_APPID: str = ""
    WECHATPAY_CERT_SERIAL: str = ""  # 商户 API 证书序列号
    WECHATPAY_PRIVATE_KEY_PATH: Path | None = None  # 商户 API 私钥文件（apiclient_key.pem）
    WECHATPAY_APIV3_KEY: SecretStr = SecretStr("")  # APIv3 密钥（32 位），解密通知用
    WECHATPAY_PUBLIC_KEY_ID: str = ""  # 微信支付公钥 ID（PUB_KEY_ID_ 开头），验签用
    WECHATPAY_PUBLIC_KEY_PATH: Path | None = None  # 微信支付公钥文件
    WECHATPAY_NOTIFY_URL: str = ""  # https://psyppt.pilipala.zj.cn/api/shop/pay/wechat/notify
    WECHATPAY_API_BASE: str = "https://api.mch.weixin.qq.com"

    # ---- 服务号网页授权（微信里付款 JSAPI 要 openid；docs/任务单/11_手机微信支付_设计.md 第五节）----
    # 服务号的 AppID 就用上面的 WECHATPAY_APPID：官方要求「获取 OpenID 的 appid 须与下单及调起支付时所使用的 appid 保持一致」，
    # 所以不另设一个 AppID，免得两边填得不一样。
    # AppSecret（开发者密码）：优先读文件（服务器 /root/xueshu-platform/secrets/wechat_mp_appsecret，容器里 /app/secrets/…），
    # 文件没配再读 WECHAT_MP_APPSECRET。两个都空 = 微信里付款整块关掉（下单页不出「微信支付」、授权接口 404），不报错。
    WECHAT_MP_APPSECRET_FILE: Path | None = None
    WECHAT_MP_APPSECRET: SecretStr = SecretStr("")
    # 公众平台配「网页授权域名」时要放在域名根上的校验文件：文件名（MP_verify_xxx.txt）和里面那一串字。
    # 平台在 https://域名/MP_verify_xxx.txt 原样回这串字；空着 = 不回（域名保存成功后可以删掉）
    WECHAT_MP_VERIFY_FILE: str = ""
    WECHAT_MP_VERIFY_CONTENT: str = ""

    # ---- 支付宝（竹涧云的支付宝；值只在 .env）----
    ALIPAY_APP_ID: str = ""
    ALIPAY_PRIVATE_KEY_PATH: Path | None = None  # 应用私钥文件
    ALIPAY_PUBLIC_KEY_PATH: Path | None = None  # 支付宝公钥文件（不是应用公钥）
    ALIPAY_NOTIFY_URL: str = ""  # https://psyppt.pilipala.zj.cn/api/shop/pay/alipay/notify
    ALIPAY_RETURN_URL: str = ""  # 付完跳回哪（只是跳回，不算付款凭据）；空 = 付款页
    ALIPAY_GATEWAY: str = "https://openapi.alipay.com/gateway.do"  # 沙箱换成沙箱网关
    ALIPAY_SELLER_ID: str = ""  # 收款支付宝账号的 UID；填了就核对通知里的 seller_id

    def methods(self) -> dict[str, str]:
        """开着的付款方式 → 支付节点 id。写错的项跳过（检查在 status()）。"""
        out: dict[str, str] = {}
        for part in self.SHOP_METHODS.split(","):
            method, _, node = part.strip().partition("=")
            method, node = method.strip(), node.strip()
            if method in METHOD_UA and node.startswith("pay."):
                out[method] = node
        return out

    def auto_confirm_platforms(self) -> list[str]:
        return [p.strip() for p in self.SHOP_AUTO_CONFIRM_PLATFORMS.split(",") if p.strip()]

    def wechat_missing(self) -> list[str]:
        need = {
            "WECHATPAY_MCHID": self.WECHATPAY_MCHID, "WECHATPAY_APPID": self.WECHATPAY_APPID,
            "WECHATPAY_CERT_SERIAL": self.WECHATPAY_CERT_SERIAL, "WECHATPAY_PRIVATE_KEY_PATH": self.WECHATPAY_PRIVATE_KEY_PATH,
            "WECHATPAY_APIV3_KEY": self.WECHATPAY_APIV3_KEY.get_secret_value(),
            "WECHATPAY_PUBLIC_KEY_ID": self.WECHATPAY_PUBLIC_KEY_ID, "WECHATPAY_PUBLIC_KEY_PATH": self.WECHATPAY_PUBLIC_KEY_PATH,
            "WECHATPAY_NOTIFY_URL": self.WECHATPAY_NOTIFY_URL,
        }
        return [k for k, v in need.items() if not v]

    def mp_appsecret(self) -> str:
        """服务号 AppSecret：文件优先（第一行），读不到再用 .env 里的值。只在换 openid 那一下读，不缓存、不打印。"""
        path = self.WECHAT_MP_APPSECRET_FILE
        if path is not None:
            try:
                first = Path(path).read_text(encoding="utf-8").strip().splitlines()
                return first[0].strip() if first else ""
            except OSError:
                return ""
        return self.WECHAT_MP_APPSECRET.get_secret_value().strip()

    def mp_verify(self) -> tuple[str, str] | None:
        """（文件名, 内容）；没配或格式不对 = None。文件名只认 MP_verify_ + 字母数字 + .txt，内容只认字母数字。"""
        name, body = self.WECHAT_MP_VERIFY_FILE.strip(), self.WECHAT_MP_VERIFY_CONTENT.strip()
        if re.fullmatch(r"MP_verify_[A-Za-z0-9]{1,64}\.txt", name) and re.fullmatch(r"[A-Za-z0-9]{1,128}", body):
            return name, body
        return None

    def alipay_missing(self) -> list[str]:
        need = {
            "ALIPAY_APP_ID": self.ALIPAY_APP_ID, "ALIPAY_PRIVATE_KEY_PATH": self.ALIPAY_PRIVATE_KEY_PATH,
            "ALIPAY_PUBLIC_KEY_PATH": self.ALIPAY_PUBLIC_KEY_PATH, "ALIPAY_NOTIFY_URL": self.ALIPAY_NOTIFY_URL,
        }
        return [k for k, v in need.items() if not v]
