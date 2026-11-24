"""服务号网页授权（snsapi_base 静默授权）：拿这位客人在服务号下的 openid。付款（shop，JSAPI 要 openid）和登录（channels，
openid 是登录身份）共用这一份；原来在 app/shop/wxoauth.py（11 号设计），12 号设计挪到底座，shop 那边原样转出去。

照官方「微信网页授权」（https://developers.weixin.qq.com/doc/service/guide/h5/auth.html）：
- 授权链接 https://open.weixin.qq.com/connect/oauth2/authorize?appid=…&redirect_uri=…&response_type=code&scope=snsapi_base
  &state=…#wechat_redirect：参数顺序不能乱（「微信会对授权链接做正则强匹配校验」），redirect_uri 要 urlEncode，
  #wechat_redirect 必须带；state 只能 a-zA-Z0-9、最多 128 字节。拼链接用 wechatpy 的 WeChatOAuth（技术栈里本来就有，顺序就是这样）。
- code 换 openid：GET https://api.weixin.qq.com/sns/oauth2/access_token?appid&secret&code&grant_type=authorization_code，
  要 AppSecret；「secret 和获取到的 access_token 安全级别都非常高，必须只保存在服务器」。code 只能用一次、5 分钟过期。
- snsapi_base 静默授权，不弹框；返回里 is_snapshotuser=1 是快照页的虚拟账号，不能拿来付款、登录。

存什么由调用方定：付款用完即扔；登录把 openid 存成登录身份（channels_logins）。网页授权的 access_token、refresh_token 一律丢掉。
日志：这里不打日志；出错只带错误码或异常类名——requests 的连接异常文字里有带 secret 的网址，绝不能拼进去。
"""

from __future__ import annotations

import hashlib
import re
import secrets
from typing import Any

import requests
from wechatpy.exceptions import WeChatOAuthException
from wechatpy.oauth import WeChatOAuth

STATE_TTL_SEC = 600  # code 5 分钟过期，state cookie 给 10 分钟够了
_STATE_RE = re.compile(r"[a-z0-9]{32}")
_OPENID_RE = re.compile(r"[A-Za-z0-9_\-]{6,128}")


class OAuthFailed(Exception):
    """换 openid 没成。reason：fail（微信报错、连不上）/ snapshot（快照页虚拟账号）。detail 里不带 secret、code、openid。"""

    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


class _OAuth(WeChatOAuth):
    """wechatpy 的网页授权，补两样：请求超时（原来没设，卡住会一直占着工人）；测试里挂假的 requests 适配器（不联网）。"""

    def __init__(self, app_id: str, secret: str, redirect_uri: str, *, state: str = "", adapter: Any = None,
                 timeout: float = 8.0) -> None:
        super().__init__(app_id, secret, redirect_uri, scope="snsapi_base", state=state)
        self.timeout = timeout
        if adapter is not None:
            self._http.mount("https://", adapter)

    def _request(self, method, url_or_endpoint, **kwargs):  # noqa: ANN001, ANN201  照父类签名
        kwargs.setdefault("timeout", self.timeout)
        return super()._request(method, url_or_endpoint, **kwargs)


def new_state() -> str:
    """32 位小写十六进制：符合官方「a-zA-Z0-9，最多 128 字节」。"""
    return secrets.token_hex(16)


def state_ok(cookie_value: str | None, state: str | None) -> bool:
    return bool(cookie_value and state and _STATE_RE.fullmatch(state) and secrets.compare_digest(cookie_value, state))


def authorize_url(appid: str, redirect_uri: str, state: str) -> str:
    return _OAuth(appid, "", redirect_uri, state=state).authorize_url


def fetch_openid(appid: str, secret: str, code: str, *, adapter: Any = None) -> str:
    """用 code 换 openid（每个 code 只能换一次）。失败抛 OAuthFailed。"""
    if not code or len(code) > 512:
        raise OAuthFailed("fail", "回调里没有 code")
    try:
        res = _OAuth(appid, secret, "", adapter=adapter).fetch_access_token(code)
    except WeChatOAuthException as e:
        raise OAuthFailed("fail", f"微信网页授权返回错误码 {e.errcode}") from None
    except requests.RequestException as e:
        raise OAuthFailed("fail", f"连不上微信网页授权接口（{type(e).__name__}）") from None
    except (KeyError, ValueError, TypeError):
        raise OAuthFailed("fail", "微信网页授权的返回看不懂") from None
    if str(res.get("is_snapshotuser") or "") == "1":
        raise OAuthFailed("snapshot", "快照页模式的虚拟账号，不能付款")
    openid = str(res.get("openid") or "")
    if not _OPENID_RE.fullmatch(openid):
        raise OAuthFailed("fail", "微信网页授权没给 openid")
    return openid


def fake_openid(code: str) -> str:
    """本机走查（jsapi 走假网关 pay.fake 时）：不连微信，按 code 造一个假 openid。"""
    return "o_fake_" + hashlib.sha256(code.encode()).hexdigest()[:21]
