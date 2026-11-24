"""制作方令牌校验（放在非路由文件里，模块 E 的制作方上传接口也复用；模块 E 设计第八节需求 6）。

请求头 `Authorization: Bearer <PRODUCTION_TOKEN>`（单独一个令牌，不用后台密码和 cookie）；没配令牌 → 503；
令牌不对 → 401，同一 IP 连错 5 次 10 分钟内不让再试（429；计数在 core.ratelimit，不在进程内存）。
"""

from __future__ import annotations

import hmac

from fastapi import HTTPException, Request, status

from app.core.deps import client_ip, get_ratelimiter
from app.intake.runtime import get_runtime

_MAX_FAILS = 5
_LOCK_SECONDS = 600


def require_production_token(request: Request) -> None:
    token = get_runtime(request.app).ctx.settings.PRODUCTION_TOKEN.get_secret_value()
    if not token:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="没配 PRODUCTION_TOKEN，制作方接口是关着的")
    limiter, ip = get_ratelimiter(request), client_ip(request)
    rule = dict(limit=_MAX_FAILS, window=_LOCK_SECONDS)
    if not limiter.test("intake.production_token_fail", ip, **rule):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail="令牌错太多次，10 分钟后再试")
    auth = request.headers.get("authorization", "")
    given = auth[7:].strip() if auth[:7].lower() == "bearer " else ""
    if not given or not hmac.compare_digest(given.encode("utf-8"), token.encode("utf-8")):
        limiter.hit("intake.production_token_fail", ip, **rule)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="令牌不对")
    if limiter.used("intake.production_token_fail", ip, **rule):
        limiter.clear("intake.production_token_fail", ip, **rule)
