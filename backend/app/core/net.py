"""跟请求来源有关的小工具。"""

from __future__ import annotations

import re

from fastapi import Request

from app.core.config import Settings


def client_ip(request: Request) -> str:
    """客户端 IP（限流、防刷用）。

    TRUST_PROXY_HEADERS=true（部署在 Cloudflare / 反向代理后面）时取 CF-Connecting-IP，
    其次 X-Forwarded-For 的第一个；否则只认直连地址（不然谁都能伪造请求头绕过限流）。
    """
    settings: Settings = request.app.state.settings
    if settings.TRUST_PROXY_HEADERS:
        cf = request.headers.get("cf-connecting-ip", "").strip()
        if cf:
            return cf
        xff = request.headers.get("x-forwarded-for", "")
        first = xff.split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


def ua_kind(ua: str) -> str:
    """按 User-Agent 分三种设备：wechat 微信里（含 MicroMessenger）/ mobile 手机浏览器 / pc 电脑。
    付款（给哪种付款方式，微信支付官方要求按 UA 分流 JSAPI 和 H5）和登录（给哪种登录方式）用同一个判断。"""
    if "MicroMessenger" in (ua or ""):
        return "wechat"
    if re.search(r"Mobile|Android|iPhone|iPad|HarmonyOS", ua or ""):
        return "mobile"
    return "pc"
