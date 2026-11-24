"""企业微信「微信客服」接口（httpx 直接调官方接口）。字段照官方文档（G4 调研，每条带出处）：

- gettoken：GET /gettoken?corpid=&corpsecret=，access_token 7200 秒，提前 5 分钟换。
- 读消息：POST /kf/sync_msg {cursor, token, limit, voice_format, open_kfid}，has_more 为真用 next_cursor 接着拉，只能拉最近 3 天。
- 发消息：POST /kf/send_msg {touser, open_kfid, msgid?, msgtype, text|image|file|...}；文字最长 2048 字节；
  只有「新接入待处理」或「智能助手接待」、客户最后一次说话后 48 小时内最多 5 条（发前我们自己先查，见 dispatch.py）。
- 欢迎语：POST /kf/send_msg_on_event {code, msgtype, text}，进入会话事件的 welcome_code，20 秒内、只能一次。
- 临时素材：POST /media/upload?type=image|voice|video|file（multipart 字段 media），media_id 3 天有效；
  GET /media/get?media_id=（成功返回文件本身，失败返回 JSON）。
- 会话状态：POST /kf/service_state/get、/kf/service_state/trans（0 未处理 1 智能助手 2 排队 3 人工 4 结束；转 3 要 servicer_userid）。
- 进线链接：POST /kf/add_contact_way {open_kfid, scene} → url（后面可拼 scene_param，≤128 字节，进入会话事件原样带回）。
- 客户昵称：POST /kf/customer/batchget {external_userid_list}。
测试用 httpx.MockTransport 做一个假的企业微信（tests/channels/fake_wecom.py），不发任何真请求。
"""

from __future__ import annotations

import re
import time
from typing import Any
from urllib.parse import unquote

import httpx

TOKEN_EXPIRED = {40014, 42001, 40001}


class WecomError(Exception):
    def __init__(self, errcode: int, errmsg: str, path: str = "") -> None:
        super().__init__(f"企业微信接口 {path} 出错：{errcode} {errmsg}")
        self.errcode = errcode
        self.errmsg = errmsg


class WecomClient:
    def __init__(
        self,
        corpid: str,
        secret: str,
        *,
        base_url: str = "https://qyapi.weixin.qq.com/cgi-bin",
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 15.0,
    ) -> None:
        self.corpid = corpid
        self._secret = secret
        self.base_url = base_url.rstrip("/")
        self._transport = transport
        self._timeout = timeout
        self._token = ""
        self._token_expire = 0.0

    def _client(self) -> httpx.AsyncClient:
        # trust_env=False：企业微信要配可信 IP，服务器直连出去，不走本机代理
        return httpx.AsyncClient(timeout=self._timeout, transport=self._transport, trust_env=False)

    async def access_token(self, *, force: bool = False) -> str:
        if not force and self._token and time.monotonic() < self._token_expire:
            return self._token
        async with self._client() as c:
            r = await c.get(f"{self.base_url}/gettoken", params={"corpid": self.corpid, "corpsecret": self._secret})
        data = r.json()
        if data.get("errcode", 0) != 0:
            raise WecomError(data.get("errcode", -1), data.get("errmsg", ""), "gettoken")
        self._token = data["access_token"]
        self._token_expire = time.monotonic() + int(data.get("expires_in", 7200)) - 300
        return self._token

    async def _post(self, path: str, body: dict[str, Any], *, retry: bool = True) -> dict[str, Any]:
        token = await self.access_token()
        async with self._client() as c:
            r = await c.post(f"{self.base_url}{path}", params={"access_token": token}, json=body)
        data = r.json()
        code = data.get("errcode", 0)
        if code in TOKEN_EXPIRED and retry:
            await self.access_token(force=True)
            return await self._post(path, body, retry=False)
        if code != 0:
            raise WecomError(code, data.get("errmsg", ""), path)
        return data

    # ---- 收 ----
    async def sync_msg(self, open_kfid: str, *, cursor: str = "", token: str = "", limit: int = 1000) -> dict[str, Any]:
        body: dict[str, Any] = {"open_kfid": open_kfid, "limit": limit, "voice_format": 0}
        if cursor:
            body["cursor"] = cursor
        if token:
            body["token"] = token
        return await self._post("/kf/sync_msg", body)

    async def get_media(self, media_id: str, *, retry: bool = True) -> tuple[bytes, str, str]:
        """返回（内容, 文件名, content-type）。"""
        token = await self.access_token()
        async with self._client() as c:
            r = await c.get(f"{self.base_url}/media/get", params={"access_token": token, "media_id": media_id})
        ctype = r.headers.get("content-type", "")
        if "application/json" in ctype or "text/plain" in ctype:
            data = r.json()
            if data.get("errcode") in TOKEN_EXPIRED and retry:
                await self.access_token(force=True)
                return await self.get_media(media_id, retry=False)
            raise WecomError(data.get("errcode", -1), data.get("errmsg", ""), "/media/get")
        return r.content, _filename_from(r.headers.get("content-disposition", "")) or media_id, ctype

    async def customer_nicknames(self, external_userids: list[str]) -> dict[str, str]:
        data = await self._post("/kf/customer/batchget", {"external_userid_list": external_userids, "need_enter_session_context": 0})
        return {c.get("external_userid", ""): c.get("nickname", "") for c in data.get("customer_list", [])}

    # ---- 发 ----
    async def send_msg(self, touser: str, open_kfid: str, msgtype: str, payload: dict[str, Any], *, msgid: str = "") -> str:
        body: dict[str, Any] = {"touser": touser, "open_kfid": open_kfid, "msgtype": msgtype, msgtype: payload}
        if msgid:
            body["msgid"] = msgid
        data = await self._post("/kf/send_msg", body)
        return data.get("msgid", "")

    async def send_msg_on_event(self, code: str, text: str) -> str:
        data = await self._post("/kf/send_msg_on_event", {"code": code, "msgtype": "text", "text": {"content": text}})
        return data.get("msgid", "")

    async def upload_media(self, media_type: str, filename: str, data: bytes, *, retry: bool = True) -> str:
        token = await self.access_token()
        async with self._client() as c:
            r = await c.post(f"{self.base_url}/media/upload", params={"access_token": token, "type": media_type},
                             files={"media": (filename, data)})
        body = r.json()
        if body.get("errcode") in TOKEN_EXPIRED and retry:
            await self.access_token(force=True)
            return await self.upload_media(media_type, filename, data, retry=False)
        if body.get("errcode", 0) != 0:
            raise WecomError(body.get("errcode", -1), body.get("errmsg", ""), "/media/upload")
        return body["media_id"]

    # ---- 会话状态、进线链接 ----
    async def service_state_get(self, open_kfid: str, external_userid: str) -> dict[str, Any]:
        return await self._post("/kf/service_state/get", {"open_kfid": open_kfid, "external_userid": external_userid})

    async def service_state_trans(self, open_kfid: str, external_userid: str, service_state: int, servicer_userid: str = "") -> dict[str, Any]:
        body: dict[str, Any] = {"open_kfid": open_kfid, "external_userid": external_userid, "service_state": service_state}
        if servicer_userid:
            body["servicer_userid"] = servicer_userid
        return await self._post("/kf/service_state/trans", body)

    async def add_contact_way(self, open_kfid: str, scene: str = "") -> str:
        body: dict[str, Any] = {"open_kfid": open_kfid}
        if scene:
            if not re.fullmatch(r"[0-9a-zA-Z_-]{1,32}", scene):
                raise ValueError("scene 只能是字母数字下划线横线，最多 32 个字符")
            body["scene"] = scene
        data = await self._post("/kf/add_contact_way", body)
        return data["url"]


def _filename_from(disposition: str) -> str:
    m = re.search(r"filename\*=(?:UTF-8'')?([^;]+)", disposition, re.I)
    if m:
        return unquote(m.group(1).strip('"'))
    m = re.search(r'filename="?([^";]+)"?', disposition, re.I)
    return unquote(m.group(1)) if m else ""
