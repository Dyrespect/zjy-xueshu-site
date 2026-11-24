"""客户侧接口的访问控制：一处实现，各路由复用（docs/任务单/12_登录与正规化_设计.md 第十节）。

每条对外接口都要说清「凭什么能访问」（scripts/check.py 规矩 24 拦），挂下面之一：
- `public`   公开：不碰任何客户的数据（图库、价目、官网设置、建新的待付款单、登录本身）。
- `by_token` 凭令牌 / 链接：令牌本身就是凭证（交付令牌、需求卡、付款页令牌、聊天 key、激活码）。令牌只管它自己那一单，
             子资源（文件号、发票号）在路由里核「是这单的」，不是一律 404。
- `webhook`  外部回调：靠验签（微信支付通知、企业微信、服务号消息推送）。
- `service`  机器对机器：工厂领交接包、制作方令牌。
- `require_customer` 要登录（当前客户）；`require_owned(db, me, customer_id)` 核「这条记录是当前客户的」，不是一律 404。
都是 FastAPI 依赖，用法：

    router = APIRouter(dependencies=[Depends(access.by_token)])          # 整个 router 都凭令牌
    @router.get("/x", dependencies=[Depends(access.public)])              # 单条
    def mine(me: Customer = Depends(access.require_customer)): ...       # 要登录

客户会话：签名 cookie `psy_sess`（itsdangerous；跟后台登录同一个 SESSION_SECRET、不同 salt），内容 {客户 id, 会话代数, 怎么登的}，
30 天，服务端不存（多进程、多机器都认）。「客户」「门」「会话代数」在入口模块（channels）里，底座不 import 业务模块：
入口模块启动时用 `set_customer_resolver` 登记两个函数（找到现在的人、某个会话是不是这个人的门）。没登记 = 一律当没登录。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from fastapi import Depends, HTTPException, Request, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer
from sqlalchemy.orm import Session

from app.core.db import get_db


COOKIE_NAME = "psy_sess"
SESSION_DAYS = 30
SESSION_MAX_AGE = SESSION_DAYS * 86400
REFRESH_AFTER = 86400  # 签发超过一天，下次问会话时顺延（重发一张新的）
_SALT = "customer-session"


# ---------------------------------------------------------------- 声明（空依赖：写明这条接口凭什么能访问）

def public() -> None:
    """公开：不碰任何客户的数据。"""


def by_token() -> None:
    """凭令牌 / 链接访问：令牌本身是凭证，子资源在路由里核是不是这一单的。"""


def webhook() -> None:
    """外部回调：靠验签。"""


def service() -> None:
    """机器对机器（工厂、制作方）：靠各自的服务令牌。"""


DECLARATIONS = ("public", "by_token", "webhook", "service", "require_customer", "owned_order")


# ---------------------------------------------------------------- 当前客户

@dataclass(frozen=True)
class CurrentCustomer:
    person_id: int  # 现在的那个人（顺着「并走了」找过的）
    method: str  # 怎么登录的：wx（微信里静默）/ qr（电脑扫码）/ sms（手机号）/ email（订单号 + 邮箱）
    issued_at: float = 0.0


# 入口模块登记：resolve(db, person_id, epoch) -> 现在的人 id 或 None（人被删了、会话代数对不上）；
# owns(db, person_id, customer_id) -> 这个会话（门）是不是这个人的
_resolve: Callable[[Session, int, int], int | None] | None = None
_owns: Callable[[Session, int, int], bool] | None = None


def set_customer_resolver(resolve: Callable[[Session, int, int], int | None], owns: Callable[[Session, int, int], bool]) -> None:
    global _resolve, _owns
    _resolve, _owns = resolve, owns


def _secret(request: Request) -> str:
    s = request.app.state.settings
    secret = s.SESSION_SECRET.get_secret_value()
    if secret:
        return secret
    from app.core.auth import dev_session_secret  # 开发时跟后台登录同一个 DATA_DIR/.session_secret

    return dev_session_secret(s.DATA_DIR)


def _serializer(request: Request) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(_secret(request), salt=_SALT)


def secure_cookie(request: Request) -> bool:
    s = request.app.state.settings
    return s.APP_ENV == "prod" or s.PUBLIC_BASE_URL.startswith("https://")


def issue_session(request: Request, response: Response, *, person_id: int, epoch: int, method: str) -> None:
    """登录成功：给这台设备发会话 cookie。"""
    token = _serializer(request).dumps({"p": int(person_id), "e": int(epoch), "m": method})
    response.set_cookie(COOKIE_NAME, token, max_age=SESSION_MAX_AGE, httponly=True, samesite="lax",
                        secure=secure_cookie(request), path="/")


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def read_session(request: Request) -> tuple[int, int, str, float] | None:
    """只核签名和 30 天，不查库：（人 id, 会话代数, 登录方式, 签发时间）。"""
    raw = request.cookies.get(COOKIE_NAME)
    if not raw or len(raw) > 512:
        return None
    try:
        data, ts = _serializer(request).loads(raw, max_age=SESSION_MAX_AGE, return_timestamp=True)
    except BadSignature:  # 含过期
        return None
    if not isinstance(data, dict) or not isinstance(data.get("p"), int):
        return None
    return int(data["p"]), int(data.get("e") or 0), str(data.get("m") or ""), ts.timestamp()


def current_customer(request: Request, db: Session) -> CurrentCustomer | None:
    got = read_session(request)
    if got is None or _resolve is None:
        return None
    pid, epoch, method, ts = got
    now_pid = _resolve(db, pid, epoch)
    if now_pid is None:
        return None
    return CurrentCustomer(person_id=now_pid, method=method, issued_at=ts)


def optional_customer(request: Request, db: Session = Depends(get_db)) -> CurrentCustomer | None:
    """登录了给当前客户，没登录给 None（不报错）。只用这个的接口还要另外声明 public / by_token。"""
    return current_customer(request, db)


def require_customer(request: Request, db: Session = Depends(get_db)) -> CurrentCustomer:
    """要登录：没登录 401（页面按这个出登录框）。"""
    me = current_customer(request, db)
    if me is None:
        raise HTTPException(401, detail="先登录")
    return me


def owns(db: Session, me: CurrentCustomer | None, customer_id: int | None) -> bool:
    return bool(me is not None and customer_id and _owns is not None and _owns(db, me.person_id, int(customer_id)))


def require_owned(db: Session, me: CurrentCustomer | None, customer_id: int | None, *, what: str = "这一单") -> None:
    """这条记录（挂在某个会话上）是不是当前客户的：不是一律 404（不说 403，不让人试出别人的东西存不存在）。"""
    if not owns(db, me, customer_id):
        raise HTTPException(404, detail=f"没有{what}")

