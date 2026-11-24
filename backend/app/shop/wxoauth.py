"""微信里付款要的服务号网页授权（snsapi_base）：实现挪到了底座 app/core/wxoauth.py（登录也用同一份，12 号设计），
这里只留付款自己的 state cookie 名字和路径，其余原样转出去，shop 的代码和测试不用改。

付款这边的规矩不变：openid 换到手就交给 JSAPI 下单，用完即扔，不落库（11 号设计第四节第 2 条）。
"""

from __future__ import annotations

from app.core.wxoauth import (STATE_TTL_SEC, OAuthFailed, authorize_url, fake_openid, fetch_openid, new_state,  # noqa: F401
                              state_ok)

STATE_COOKIE = "psy_wxo"  # 防 CSRF：发起授权时种下的随机串，回来时和 state 比
COOKIE_PATH = "/api/shop/wx"
