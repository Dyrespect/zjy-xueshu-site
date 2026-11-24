"""官网设置（存在 website_kv 的 settings 一条，后台「官网」页改；没改过就用这里的默认值）。

主体信息出处：psyppt静态站/build.py（公司全称、统一社会信用代码、ICP 备案号）；联系电话是 Edison 11-18 深夜给的，对外公开，
微信同号。公安联网备案号 Edison 备案后填，空着时页脚不显示那一行。邮箱、地址、客服时间没给过，空着不显示，不编。
「公开给搜索引擎」默认关（现在线上站带 noindex，正式开放由 Edison 决定）；「维护中」默认关。
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy.orm import Session

from app.core.db import utcnow
from app.core.events import record_event
from app.website.models import WebsiteKV

# 后台「官网」页上，这几项空着会标「待填」（正式开放前要补的）
LAUNCH_FIELDS: dict[str, str] = {
    "police_beian": "公安联网备案号（网站开通后到全国互联网安全管理服务平台备案，拿到号填这里）",
    "email": "对外邮箱（隐私和投诉的书面渠道；没有就只留电话）",
    "service_hours": "客服时间（写了客人知道什么时候有人回）",
}


class WebsiteConfig(BaseModel):
    model_config = ConfigDict(extra="ignore")

    company_name: str = Field(default="杭州竹涧云科技有限公司", min_length=2, max_length=60)
    credit_code: str = Field(default="91330110MAKFUNHCXY", max_length=24)
    icp: str = Field(default="浙ICP备2026046510号-1", max_length=40)
    police_beian: str = Field(default="", max_length=40)  # 例「浙公网安备33010002000001号」；空 = 不显示
    phone: str = Field(default="15068998671", max_length=20)
    phone_note: str = Field(default="微信同号", max_length=20)
    email: str = Field(default="", max_length=80)
    address: str = Field(default="", max_length=120)
    service_hours: str = Field(default="", max_length=40)
    # 投诉多久答复：我的建议（1 个工作日内），Edison 可改
    reply_promise: str = Field(default="一般 1 个工作日内答复", max_length=60)
    indexable: bool = False  # 公开给搜索引擎：关 = robots.txt 全站不让爬、页面带 noindex
    maintenance: bool = False  # 维护中：开了以后官网、下单、付款页显示维护中（后台、交付页照常）
    maintenance_text: str = Field(default="网站正在维护，预计很快恢复。如有急事，请拨打客服电话。", max_length=120)
    # 自有网页暂不收款（商户号没下来、SHOP_METHODS 空着）时，下单页「去付款」换成去这两个平台下单：
    # 店铺链接选填，空着只显示「小红书」「闲鱼」字样；另可写一句怎么找到店（如「两个平台都搜：心理学汇报 PPT 定制」）
    xhs_shop_url: str = Field(default="", max_length=300)
    xianyu_shop_url: str = Field(default="", max_length=300)
    platform_shop_note: str = Field(default="", max_length=80)
    # 营业执照公示页 /license（《电子商务法》第十五条：首页显著位置持续公示营业执照信息或链接；12 号设计第十一节）。
    # 默认值照营业执照电子版（2026-11-18 Edison 给的图）；执照变更后在后台改（《网络交易监督管理办法》第十二条：十个工作日内更新）
    license_type: str = Field(default="有限责任公司（自然人独资）", max_length=40)
    legal_rep: str = Field(default="戴敬力", max_length=20)
    reg_address: str = Field(default="浙江省杭州市余杭区仓前街道文一西路1378号1幢E座1906-18室", max_length=120)
    established: str = Field(default="2026-06-09", max_length=20)
    registry_authority: str = Field(default="杭州市余杭区市场监督管理局", max_length=40)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        v = v.strip()
        if v and not re.fullmatch(r"\+?[0-9][0-9 -]{5,18}", v):
            raise ValueError("电话只写数字（可带 + 和 -），例 15068998671")
        return v

    @field_validator("email")
    @classmethod
    def _email(cls, v: str) -> str:
        v = v.strip()
        if v and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v):
            raise ValueError("邮箱格式不对，例 kefu@example.com")
        return v

    @field_validator("xhs_shop_url", "xianyu_shop_url")
    @classmethod
    def _shop_url(cls, v: str) -> str:
        v = v.strip()
        if v and not re.fullmatch(r"https://[^\s<>\"']+", v):
            raise ValueError("店铺链接要用 https:// 开头的完整网址（从平台 App 里「分享店铺」复制）")
        return v

    @field_validator("credit_code")
    @classmethod
    def _credit(cls, v: str) -> str:
        v = v.strip().upper()
        if v and not re.fullmatch(r"[0-9A-Z]{18}", v):
            raise ValueError("统一社会信用代码是 18 位数字或大写字母")
        return v

    def police_code(self) -> str:
        """公安备案号里的数字（拼查询链接用）。"""
        return "".join(re.findall(r"\d", self.police_beian))

    def pending_launch(self) -> list[str]:
        return [k for k in LAUNCH_FIELDS if not str(getattr(self, k)).strip()]


def load_config(db: Session) -> WebsiteConfig:
    row = db.get(WebsiteKV, "settings")
    return WebsiteConfig.model_validate(row.value if row is not None else {})


def save_config(db: Session, data: dict, *, by: str) -> WebsiteConfig:
    """校验后存；记 website.config_changed（改了哪些字段、改前改后）。调用方提交。"""
    before = load_config(db)
    cfg = WebsiteConfig.model_validate({**before.model_dump(), **data})
    changed = [k for k, v in cfg.model_dump().items() if getattr(before, k) != v]
    row = db.get(WebsiteKV, "settings")
    if row is None:
        row = WebsiteKV(key="settings")
        db.add(row)
    row.value, row.updated_at, row.by = cfg.model_dump(), utcnow(), by[:32]
    record_event(db, "website.config_changed", "website:settings", {
        "fields": changed, "before": {k: getattr(before, k) for k in changed},
        "after": {k: getattr(cfg, k) for k in changed}, "by": by})
    return cfg


def public_view(cfg: WebsiteConfig) -> dict:
    """给页面的：页脚、联系我们、维护中、noindex 要用的全部字段（都是对外公开的信息）。"""
    code = cfg.police_code()
    return {
        **cfg.model_dump(),
        "police_beian_url": f"https://beian.mps.gov.cn/#/query/webSearch?code={code}" if code else "",
        "icp_url": "https://beian.miit.gov.cn/",
    }
