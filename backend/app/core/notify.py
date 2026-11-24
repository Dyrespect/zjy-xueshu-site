"""通知 Edison：一个接口，外面一层通知策略，里面几种发法（FEISHU_SENDER 选，默认 auto）。

业务代码只调 `notifier.send("出图失败：xxx", link="/admin/orders", level="urgent", kind="出图失败", who=f"order:{id}")`。
- level（必须写，scripts/check.py 规矩 N1 拦）：urgent 立刻推 / digest 不推、进日报「需要你看一眼的」/ count 不推、日报只给个数。
  推不推、同类同一客人 10 分钟合并、每小时上限由 app.core.notify_policy.PolicyNotifier 管（网站里 app.state.notifier 就是它）。
- 具体发法：飞书应用机器人（FEISHU_APP_FILE，现在用 Ruler）私聊发给 Edison，富文本，正文先脱敏，末尾一行「打开后台」链接
  （没给 link 就链后台首页）；飞书群自定义机器人（FEISHU_WEBHOOK）发到群里，纯文字；都没配只写日志。
- 发送失败：写日志、不抛异常——通知失败不能把业务流程打断。
- 测试：用 `FakeNotifier`，发过的话都在 `.sent` 里（不管级别），链接、级别、类别在 `.links`、`.levels`、`.kinds` 里。

**凭证是密钥**：App Secret、tenant_access_token 不进日志、事件、库、后台接口；接收人编号（receive_id）也不打印（scripts/check.py 规矩 19）。
"""

from __future__ import annotations

import base64
import functools
import hashlib
import hmac
import json
import logging
import threading
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import anyio
import httpx

from app.core.config import Settings
from app.core.redact import redact_text

if TYPE_CHECKING:
    from app.core.db import Database

log = logging.getLogger("app.notify")

Level = Literal["urgent", "digest", "count"]
LEVELS: tuple[str, ...] = ("urgent", "digest", "count")


def full_link(base_url: str, link: str) -> str:
    """后台页面 → 飞书里点得开的完整网址；已经是完整网址的原样返回。"""
    if not link:
        return ""
    if link.startswith(("https://", "http://")):
        return link
    return base_url.rstrip("/") + (link if link.startswith("/") else "/" + link)


class Notifier(ABC):
    @abstractmethod
    def send(self, text: str, link: str = "", *, level: Level = "digest", kind: str = "", who: str = "") -> bool:
        """发一条通知。link：后台页面（如 /admin/conversations/3）；level：urgent / digest / count（见文件头）；
        kind：类别（日报按它归拢、合并用，如「出图失败」）；who：哪位客人或哪一单（同类同一个 10 分钟合并，如 customer:3）。
        成功（或只写日志、排进队列）返回 True，发送失败返回 False。具体发法收到就发，级别只给通知策略看。"""

    async def asend(self, text: str, link: str = "", *, level: Level = "digest", kind: str = "", who: str = "") -> bool:
        return await anyio.to_thread.run_sync(functools.partial(self.send, text, link, level=level, kind=kind, who=who))


def unwrap(notifier: Notifier) -> Notifier:
    """外面包着通知策略时取里面真正发消息的那个（运维告警、日报有自己的推送规则，直接用它发）。"""
    return getattr(notifier, "inner", notifier)


class LogNotifier(Notifier):
    def send(self, text: str, link: str = "", *, level: Level = "digest", kind: str = "", who: str = "") -> bool:
        log.info("[通知，没配飞书，只写日志] %s%s", text, f"（{link}）" if link else "")
        return True


class FeishuNotifier(Notifier):
    """飞书自定义机器人。开了签名校验就传 secret。

    文档：https://open.feishu.cn/document/client-docs/bot-v3/add-custom-bot
    """

    def __init__(
        self,
        webhook: str,
        secret: str = "",
        *,
        base_url: str = "",
        timeout: float = 5.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.webhook = webhook
        self.secret = secret
        self.base_url = base_url
        self.timeout = timeout
        self._transport = transport  # 测试时注入 MockTransport

    def _sign(self, timestamp: int) -> str:
        string_to_sign = f"{timestamp}\n{self.secret}".encode()
        digest = hmac.new(string_to_sign, b"", digestmod=hashlib.sha256).digest()
        return base64.b64encode(digest).decode()

    def build_payload(self, text: str) -> dict:
        payload: dict = {"msg_type": "text", "content": {"text": text}}
        if self.secret:
            ts = int(time.time())
            payload["timestamp"] = str(ts)
            payload["sign"] = self._sign(ts)
        return payload

    def send(self, text: str, link: str = "", *, level: Level = "digest", kind: str = "", who: str = "") -> bool:
        if link:
            text = f"{text}\n后台：{full_link(self.base_url, link)}"
        try:
            with httpx.Client(timeout=self.timeout, transport=self._transport) as client:
                resp = client.post(self.webhook, json=self.build_payload(text))
            data = resp.json() if resp.content else {}
            code = data.get("code", data.get("StatusCode", 0))
            if resp.status_code != 200 or code not in (0, None):
                log.warning("飞书通知失败：HTTP %s %s", resp.status_code, data)
                return False
            return True
        except Exception as e:  # 网络错、JSON 错都只记日志
            log.warning("飞书通知异常：%s", e)
            return False


# ---------------------------------------------------------------- 飞书应用机器人（自建应用，如 Ruler）

RECEIVE_ID_TYPES = ("open_id", "chat_id", "user_id", "union_id", "email")
FEISHU_API = "https://open.feishu.cn"
# 用 App ID / App Secret 换 tenant_access_token：官方 SDK lark-oapi 1.8.0（2026-11-16）用的也是这个地址（另一个
# accounts.feishu.cn/oauth/v3/token 是它的 client assertion 模式才用）。文档：
# https://open.feishu.cn/document/server-docs/authentication-management/access-token/tenant_access_token_internal
TOKEN_PATH = "/open-apis/auth/v3/tenant_access_token/internal"
# 发消息：https://open.feishu.cn/document/server-docs/im-v1/message/create
SEND_PATH = "/open-apis/im/v1/messages"
TOKEN_BAD = {99991661, 99991663, 99991665, 99991671}  # 令牌没带、过期、非法：换一个，重试一次
RATE_LIMITED = {99991400, 230020}  # 接口限频、发消息限频（HTTP 也可能是 429）
MAX_BODY = 30 * 1024  # 富文本、卡片消息请求体上限 30 KB


@dataclass(frozen=True)
class FeishuAppCredentials:
    """凭证文件里的四样（repr 不带密钥和接收人）。"""

    app_id: str
    app_secret: str = field(repr=False)
    receive_id: str = field(repr=False)
    receive_id_type: str = "chat_id"
    api_base: str = FEISHU_API


def read_app_file(path: Path | None) -> FeishuAppCredentials | None:
    """读 FEISHU_APP_FILE（JSON：app_id、app_secret、receive_id、receive_id_type，可选 api_base）。

    没配、读不了、缺字段都算没配：记一行日志说缺哪样（不写值），返回 None。只在通知层里用，结果不许打印。
    """
    if path is None:
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log.warning("飞书应用机器人的凭证文件读不了（%s），通知只写日志", type(e).__name__)
        return None
    if not isinstance(data, dict):
        log.warning("飞书应用机器人的凭证文件不是 JSON 对象，通知只写日志")
        return None
    got = {k: str(data.get(k) or "").strip() for k in ("app_id", "app_secret", "receive_id", "receive_id_type", "api_base")}
    got["receive_id_type"] = got["receive_id_type"] or "chat_id"
    got["api_base"] = (got["api_base"] or FEISHU_API).rstrip("/")
    missing = [k for k in ("app_id", "app_secret", "receive_id") if not got[k]]
    if got["receive_id_type"] not in RECEIVE_ID_TYPES:
        missing.append("receive_id_type（只能是 " + " / ".join(RECEIVE_ID_TYPES) + "）")
    if not got["api_base"].startswith("https://"):
        missing.append("api_base（要 https://）")
    if missing:
        log.warning("飞书应用机器人的凭证文件缺：%s，通知只写日志", "、".join(missing))
        return None
    return FeishuAppCredentials(**got)


def _json(resp: httpx.Response) -> dict[str, Any]:
    try:
        data = resp.json() if resp.content else {}
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _reset_seconds(resp: httpx.Response) -> float:
    """限频时等几秒：照响应头 x-ogw-ratelimit-reset，夹在 0.5–2 秒（发送在请求里或后台线程里，不能等太久）。"""
    try:
        return min(2.0, max(0.5, float(resp.headers.get("x-ogw-ratelimit-reset", "1"))))
    except ValueError:
        return 1.0


class FeishuAppClient:
    """飞书自建应用发消息：App ID / App Secret 换 tenant_access_token（缓存，到期前 10 分钟换新），调 im/v1/messages。

    - 令牌每个进程自己换、自己缓存。官方文档：剩余有效期不到 30 分钟时再取会给一个新的，新旧同时有效——
      所以同一个应用在几处（Hermes 里的 Ruler、这里的网站进程）各自取令牌互不作废。
    - 频率：向同一用户 / 同一群发消息 5 QPS（和 Hermes 那边共用）。这里同一时刻只发一条、两条之间至少隔 min_interval 秒；
      遇到限频（HTTP 429、99991400、230020）按 x-ogw-ratelimit-reset 等一下（最多 2 秒）重试一次。
    - 每条带 uuid：重试时同一条不会发两遍（官方：同一 uuid 1 小时内最多成功发一条）。
    - 不抛异常：返回（发出去没有，没发出去的原因）；原因里不带令牌、密钥、接收人编号。
    """

    def __init__(
        self,
        creds: FeishuAppCredentials,
        *,
        timeout: float = 5.0,
        transport: httpx.BaseTransport | None = None,
        min_interval: float = 0.25,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._creds = creds
        self.timeout = timeout
        self._transport = transport
        self.min_interval = min_interval
        self._sleep = sleep
        self._clock = clock
        self._lock = threading.Lock()
        self._token = ""
        self._token_until = 0.0
        self._last_send = float("-inf")

    @property
    def receive_id_type(self) -> str:
        return self._creds.receive_id_type

    def _scrub(self, why: str) -> str:
        for s in (self._creds.app_secret, self._creds.receive_id, self._token):
            if s:
                why = why.replace(s, "***")
        return redact_text(why)

    def _fetch_token(self, c: httpx.Client) -> str:
        """换令牌；失败抛 RuntimeError（说明里只有飞书的错误码）。调用方拿着锁。"""
        now = self._clock()
        if self._token and now < self._token_until:
            return self._token
        r = c.post(TOKEN_PATH, json={"app_id": self._creds.app_id, "app_secret": self._creds.app_secret})
        data = _json(r)
        got = str(data.get("tenant_access_token") or "")
        if r.status_code != 200 or data.get("code") != 0 or not got:
            self._token, self._token_until = "", 0.0
            raise RuntimeError(f"换令牌失败：HTTP {r.status_code}，飞书回 code={data.get('code')} {str(data.get('msg', ''))[:80]}")
        expire = int(data.get("expire") or 7200)
        self._token, self._token_until = got, now + max(60, expire - 600)
        return got

    def send(self, msg_type: str, content: dict[str, Any]) -> tuple[bool, str]:
        body = {"receive_id": self._creds.receive_id, "msg_type": msg_type,
                "content": json.dumps(content, ensure_ascii=False), "uuid": uuid.uuid4().hex}
        size = len(json.dumps(body, ensure_ascii=False).encode())
        if size > MAX_BODY:
            return False, f"消息太长（{size} 字节，飞书富文本上限 30 KB）"
        with self._lock:
            try:
                with httpx.Client(base_url=self._creds.api_base, timeout=self.timeout, transport=self._transport) as c:
                    return self._send_locked(c, body)
            except Exception as e:  # noqa: BLE001  网络错、换令牌失败都只记原因，不抛
                why = str(e) if isinstance(e, RuntimeError) else type(e).__name__
                return False, self._scrub(why)

    def _send_locked(self, c: httpx.Client, body: dict[str, Any]) -> tuple[bool, str]:
        retried_token = retried_rate = False
        while True:
            token = self._fetch_token(c)
            wait = self._last_send + self.min_interval - self._clock()
            if wait > 0:
                self._sleep(wait)
            self._last_send = self._clock()
            r = c.post(SEND_PATH, params={"receive_id_type": self._creds.receive_id_type}, json=body,
                       headers={"Authorization": f"Bearer {token}"})
            data = _json(r)
            code = data.get("code")
            if r.status_code == 200 and code == 0:
                return True, ""
            if code in TOKEN_BAD and not retried_token:
                retried_token = True
                self._token, self._token_until = "", 0.0
                continue
            if (r.status_code == 429 or code in RATE_LIMITED) and not retried_rate:
                retried_rate = True
                self._sleep(_reset_seconds(r))
                continue
            return False, self._scrub(f"HTTP {r.status_code}，飞书回 code={code} {str(data.get('msg', ''))[:80]}")


def app_post(text: str, url: str) -> dict[str, Any]:
    """业务通知 → 飞书富文本 post 的 content：正文一段 + 一行「打开后台」。"""
    rows: list[list[dict[str, Any]]] = [[{"tag": "text", "text": text}]]
    if url:
        rows.append([{"tag": "a", "text": "打开后台", "href": url}])
    return {"zh_cn": {"content": rows}}


class FeishuAppNotifier(Notifier):
    """飞书应用机器人（现在是 Ruler，私聊发给 Edison）：正文先按 app.core.redact 脱敏（手机号、激活码全文、税号、邮箱用户名、
    带令牌的网址……），末尾一行后台链接（没给 link 就链 /admin）。当场发、不抛异常，发不出去写一行日志。
    推不推、合并、每小时上限归外面的通知策略（app.core.notify_policy.PolicyNotifier）管，它在后台线程里调这里。"""

    name = "feishu_app"

    def __init__(self, client: FeishuAppClient, *, base_url: str, source: str = "") -> None:
        self.client = client
        self.base_url = base_url
        self.source = source  # 后台显示「凭证读自哪」（文件路径，不是密钥）

    def content(self, text: str, link: str = "") -> dict[str, Any]:
        return app_post(redact_text(text), full_link(self.base_url, link or "/admin"))

    def send(self, text: str, link: str = "", *, level: Level = "digest", kind: str = "", who: str = "") -> bool:
        ok, why = self.client.send("post", self.content(text, link))
        if not ok:
            log.warning("飞书应用机器人没发出去：%s", why)
        return ok


class FakeNotifier(Notifier):
    """测试用：不发任何请求，记下每一条（不管级别）：话 .sent、链接 .links、级别 .levels、类别 .kinds、对象 .whos。"""

    def __init__(self) -> None:
        self.sent: list[str] = []
        self.links: list[str] = []
        self.levels: list[str] = []
        self.kinds: list[str] = []
        self.whos: list[str] = []

    def send(self, text: str, link: str = "", *, level: Level = "digest", kind: str = "", who: str = "") -> bool:
        self.sent.append(text)
        self.links.append(link)
        self.levels.append(level)
        self.kinds.append(kind)
        self.whos.append(who)
        return True

    def of(self, level: str) -> list[str]:
        """某一级别的话。"""
        return [t for t, lv in zip(self.sent, self.levels) if lv == level]


def build_sender(settings: Settings, *, transport: httpx.BaseTransport | None = None) -> Notifier:
    """具体发法，按 FEISHU_SENDER 选：auto = 应用机器人（FEISHU_APP_FILE 读得到）> 群机器人（FEISHU_WEBHOOK）> 只写日志。"""
    mode = settings.FEISHU_SENDER
    base = settings.PUBLIC_BASE_URL
    if mode in ("auto", "app"):
        creds = read_app_file(settings.FEISHU_APP_FILE)
        if creds is not None:
            return FeishuAppNotifier(FeishuAppClient(creds, transport=transport), base_url=base, source=f"文件 {settings.FEISHU_APP_FILE}")
        if mode == "app":
            log.warning("FEISHU_SENDER=app 但 FEISHU_APP_FILE 没配好，通知只写日志")
            return LogNotifier()
    webhook = settings.FEISHU_WEBHOOK.get_secret_value()
    if mode in ("auto", "webhook") and webhook:
        return FeishuNotifier(webhook, settings.FEISHU_SECRET.get_secret_value(), base_url=base, transport=transport)
    return LogNotifier()


def build_notifier(settings: Settings, database: Database | None = None, *,
                   transport: httpx.BaseTransport | None = None) -> Notifier:
    """网站用的通知：给了库就在具体发法外面包一层通知策略（推不推、合并、上限、记进日报）；不给库就是光秃秃的发法。"""
    inner = build_sender(settings, transport=transport)
    if database is None:
        return inner
    from app.core.notify_policy import PolicyNotifier  # notify_policy 要 import 本文件的 Notifier

    return PolicyNotifier(inner, database, merge_minutes=settings.NOTIFY_MERGE_MINUTES, urgent_per_hour=settings.NOTIFY_URGENT_PER_HOUR)
