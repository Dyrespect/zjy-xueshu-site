"""后台登录：只有 Edison 一个人用，一个密码（ADMIN_PASSWORD），签名 cookie 会话。

- 接口：POST /api/auth/login {password}、POST /api/auth/logout、GET /api/auth/me
- 保护后台接口：`Depends(require_admin)`。admin 模块的 router 已经整体挂了这个依赖。
- ADMIN_PASSWORD 没配：一律登录失败（503），不会有空密码能进的情况。
- SESSION_SECRET 没配：开发时随机生成一个存到 DATA_DIR/.session_secret（同一台机器上几个网站进程共用、重启不掉登录）；
  APP_ENV=prod 时启动直接报错（多台机器必须配同一个）。会话就是签名 cookie，服务端不存，多进程多机器都认。
- 同一 IP 连续输错 5 次，10 分钟内不让再试（计数在 core.ratelimit，不在进程内存）。
"""

from __future__ import annotations

import hmac
import logging
import os
import secrets
import time
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response, status
from itsdangerous import BadSignature, URLSafeTimedSerializer
from pydantic import BaseModel

from app.core.config import Settings
from app.core.net import client_ip
from app.core.ratelimit import RateLimits

log = logging.getLogger("app.auth")

COOKIE_NAME = "admin_session"
_MAX_FAILS = 5
_LOCK_SECONDS = 600


FAIL_BUCKET = "auth.login_fail"


def dev_session_secret(data_dir: Path) -> str:
    """开发用：DATA_DIR/.session_secret，没有就建（O_EXCL，几个进程同时起只有一个写成，别的读它的）。"""
    path = data_dir / ".session_secret"
    data_dir.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        for _ in range(50):
            text = path.read_text(encoding="utf-8").strip()
            if text:
                return text
            time.sleep(0.02)
        raise RuntimeError(f"{path} 是空的：删掉它再启动")
    secret = secrets.token_urlsafe(32)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(secret)
    return secret


class AuthManager:
    """放在 app.state.auth。"""

    def __init__(self, settings: Settings, limiter: RateLimits) -> None:
        secret = settings.SESSION_SECRET.get_secret_value()
        if not secret:
            secret = dev_session_secret(settings.DATA_DIR)
            log.warning("SESSION_SECRET 没配，用 DATA_DIR/.session_secret（只适合本机开发）")
        self._password = settings.ADMIN_PASSWORD.get_secret_value()
        self._serializer = URLSafeTimedSerializer(secret, salt="admin-session")
        self.max_age = settings.SESSION_MAX_AGE_DAYS * 86400
        # 生产（APP_ENV=prod）一律带 Secure：Cloudflare 回源到 nginx 可能是 http，不能按请求的协议判断
        self.secure_cookie = settings.APP_ENV == "prod" or settings.PUBLIC_BASE_URL.startswith("https://")
        self._limiter = limiter

    @property
    def configured(self) -> bool:
        return bool(self._password)

    def locked(self, ip: str) -> bool:
        return not self._limiter.test(FAIL_BUCKET, ip, limit=_MAX_FAILS, window=_LOCK_SECONDS)

    def check_password(self, ip: str, password: str) -> bool:
        ok = self.configured and hmac.compare_digest(
            password.encode("utf-8"), self._password.encode("utf-8")
        )
        if ok:
            self._limiter.clear(FAIL_BUCKET, ip, limit=_MAX_FAILS, window=_LOCK_SECONDS)
        else:
            self._limiter.hit(FAIL_BUCKET, ip, limit=_MAX_FAILS, window=_LOCK_SECONDS)
        return ok

    def issue(self) -> str:
        return self._serializer.dumps({"admin": True})

    def verify(self, token: str | None) -> bool:
        if not token:
            return False
        try:
            data = self._serializer.loads(token, max_age=self.max_age)
        except BadSignature:  # 含过期（SignatureExpired 是它的子类）
            return False
        return isinstance(data, dict) and data.get("admin") is True


def _auth(request: Request) -> AuthManager:
    return request.app.state.auth


def is_admin(request: Request) -> bool:
    return _auth(request).verify(request.cookies.get(COOKIE_NAME))


def require_admin(request: Request) -> None:
    """依赖注入：没登录返回 401。"""
    if not is_admin(request):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="请先登录后台")


class LoginIn(BaseModel):
    password: str


class MeOut(BaseModel):
    admin: bool


router = APIRouter()


@router.post("/login", response_model=MeOut)
def login(body: LoginIn, request: Request, response: Response) -> MeOut:
    auth = _auth(request)
    ip = client_ip(request)
    if not auth.configured:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail="后台密码未配置（ADMIN_PASSWORD）")
    if auth.locked(ip):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail="输错次数太多，10 分钟后再试")
    if not auth.check_password(ip, body.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="密码不对")
    response.set_cookie(
        COOKIE_NAME,
        auth.issue(),
        max_age=auth.max_age,
        httponly=True,
        samesite="lax",
        secure=auth.secure_cookie,
        path="/",
    )
    return MeOut(admin=True)


@router.post("/logout", response_model=MeOut)
def logout(response: Response) -> MeOut:
    response.delete_cookie(COOKIE_NAME, path="/")
    return MeOut(admin=False)


@router.get("/me", response_model=MeOut)
def me(request: Request) -> MeOut:
    return MeOut(admin=is_admin(request))
