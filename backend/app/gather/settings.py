"""聚人模块的配置（读同一个 .env）。运行中要改的（核验方式、插件名字、几段文案）在后台「聚人设置」，存库里（config.py）。

测试里：`GatherSettings(_env_file=None, SITE_FIGURES_URL=...)` 放到 `app.state.gather_settings`。
"""

from __future__ import annotations

from app.core.config import ModuleSettings


class GatherSettings(ModuleSettings):
    # ---- 统一站点：三块各自的网址前缀（不写死域名）。空 = 和当前页面同一个域名（本机开发、同域部署时）----
    # 官网（价目、交付说明、退款与售后、关于我们；psyppt 静态站），如 https://psyppt.pilipala.zj.cn
    SITE_MAIN_URL: str = ""
    # 下单页、兑换页（支付回调、微信客服回调也在这个域名），如 https://psyppt.pilipala.zj.cn
    SITE_APP_URL: str = ""
    # 图库网站（建议单独的子域名：转发换下载被微信拦，拦的是域名，不能连带支付回调；07 设计第六节第 7 条）
    SITE_FIGURES_URL: str = ""
    # 页脚：公司全称、统一社会信用代码、备案号（和官网、下单页同一套；出处：psyppt静态站/build.py、blocks/shop-frame）
    SITE_COMPANY: str = "杭州竹涧云科技有限公司"
    SITE_CREDIT_CODE: str = "91330110MAKFUNHCXY"
    SITE_ICP: str = "浙ICP备2026046510号-1"

    # ---- 来源记账 ----
    # 链接里 from= 的白名单；不在里面的记成 other（07 第十一节检查 5）
    FUNNEL_SOURCES: list[str] = ["gzh", "xhs", "dy", "share", "github", "ai", "skill", "pack", "site", "search", "other"]
    # 同一访客多少分钟内只记一次来访
    FUNNEL_DEDUPE_MINUTES: int = 30

    # ---- 防刷（同一 IP 每小时）----
    GATHER_RATE_PER_HOUR: int = 20  # 发起领取、交截图、重发
    OPEN_API_RATE_PER_HOUR: int = 60  # 开放接口、插件（拍的数，上线后看日志再改）
    VISIT_RATE_PER_HOUR: int = 300
    # 截图最大几 MB
    GATHER_EVIDENCE_MAX_MB: int = 5
