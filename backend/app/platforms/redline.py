"""红线词表（只有这一份）：平台文案、发货内容、商品页不许出现的词。

谁读：scripts/check.py（规矩 11 静态扫，用 ast 读这里的 TIERS / PATTERNS，不 import）、后台保存设置时校验发货模板、
模块 G 的 copy.lint。主窗口 11-18 裁决（渠道与支付设计冲突 7）：词表放这里，别处不另写。
分档照模块 G 设计第七节：all 所有对外文字；platform 平台上另加；platform_dy 抖音再加；gzh_allow 公众号里放过的。
模块 A 先按 G 的设计播了种，内容归模块 C、G 维护。
"""

from __future__ import annotations

import re

TIERS: dict[str, tuple[str, ...]] = {
    # 联系方式和谐音、学术红线、绝对化用语
    "all": (
        "微信", "weixin", "wechat", "vx", "VX", "Vx", "v信", "V信", "薇信", "威信", "徽信", "绿泡泡", "扣扣", "QQ",
        "加V", "加v", "+V", "+v", "加我", "二维码", "扫码", "扫一扫", "手机号",
        "代写", "代做", "代考", "枪手", "包过", "保过", "降重",
        "最好", "最佳", "最强", "最专业", "第一", "首个", "首家", "唯一", "顶级", "全网", "100%", "百分百", "绝对",
    ),
    "platform": (
        "公众号", "企业微信", "企微", "PsyEngine", "闲鱼", "小红书", "抖音", "淘宝", "拼多多", "微店",
        "私下", "线下交易", "站外", "主页有", "看签名", "找文献", "查文献", "文献检索", "润色",
        "wx", "WX", "群号",  # 渠道与支付设计第六节 gate.platform_text 的词表补的
    ),
    "platform_dy": ("开题报告",),
    "gzh_allow": ("微信客服", "公众号"),
}

PATTERNS: dict[str, str] = {
    "手机号": r"(?<!\d)1[3-9]\d{9}(?!\d)",
    "邮箱": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    "微信号": r"wxid_[A-Za-z0-9_-]{4,}",
}

# 网址（不放进 PATTERNS：check.py 规矩 11 会拿 PATTERNS 扫代码，网址在代码里是正常的）。
# 某个平台查实不许发货内容里放外部网址时（渠道档案 allow_url=false），发货文案里的网址都算命中；
# 允许时，只有兑换网址那个域名能出现。渠道与支付设计第六节 gate.platform_text、第八节冲突 5。
URL_PATTERN = r"(?i)\b(?:https?://)?((?:[a-z0-9-]+\.)+(?:cn|com|net|org|top|xyz|io|me|cc|vip|link))(?:[/:?#][^\s]*)?"


def find_urls(text: str, allow_hosts: tuple[str, ...] = ()) -> list[str]:
    """文字里的网址（域名）；allow_hosts 里的域名（和它的子域名）不算。"""
    out = []
    for m in re.finditer(URL_PATTERN, text or ""):
        host = m.group(1).lower()
        if any(host == h or host.endswith("." + h) for h in allow_hosts if h):
            continue
        out.append(f"网址 {host}")
    return out


def words_for(tier: str) -> tuple[str, ...]:
    """某一档要查的词（platform_dy = all + platform + platform_dy；platform = all + platform）。"""
    out = list(TIERS["all"])
    if tier in ("platform", "platform_dy"):
        out += TIERS["platform"]
    if tier == "platform_dy":
        out += TIERS["platform_dy"]
    if tier == "gzh":
        out = [w for w in out if w not in TIERS["gzh_allow"]]
    return tuple(out)


def find(text: str, tier: str = "platform") -> list[str]:
    """文字里出现的红线词 / 联系方式。"""
    hits = sorted({w for w in words_for(tier) if w in (text or "")})
    for name, pat in PATTERNS.items():
        if re.search(pat, text or ""):
            hits.append(name)
    return hits
