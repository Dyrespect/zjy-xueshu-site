"""假的企业微信（httpx.MockTransport）：照官方文档的地址和字段回话，把收发链路测通，不发任何真请求。

- gettoken / kf/sync_msg（带 cursor 分页、has_more）/ kf/send_msg / kf/send_msg_on_event / media/upload /
  media/get / kf/service_state/get / kf/service_state/trans / kf/add_contact_way / kf/customer/batchget
- 发消息时也按官方规则卡 48 小时 / 5 条（errcode 95002），用来证明我们自己发前就拦住了，不靠它报错。
"""

from __future__ import annotations

import json
import time
from typing import Any
from urllib.parse import quote

import httpx

from tests.intake.helpers import PDF_BYTES

CORPID = "wx5823bf96d3bd56c7"
SECRET = "fake-kf-secret"
KFID = "wkAJ2GCAAAZSfhHCt7IFSvLKtMPxyJTw"


class FakeWecom:
    def __init__(self, page_size: int = 2) -> None:
        self.page_size = page_size
        self.inbox: list[dict[str, Any]] = []  # 待客户「发」的消息（sync_msg 拉的就是它）
        self.sent: list[dict[str, Any]] = []
        self.events_sent: list[dict[str, Any]] = []
        self.uploads: list[dict[str, Any]] = []
        self.trans: list[dict[str, Any]] = []
        self.media: dict[str, tuple[bytes, str]] = {"MEDIA_PDF": (PDF_BYTES, "开题报告-阿杭.pdf"), "MEDIA_VOICE": (b"#!AMR\n", "v.amr")}
        self.tokens_issued = 0
        self.expire_next = False
        self.calls: list[str] = []
        self.last_customer_time: dict[str, float] = {}
        self.sent_since: dict[str, int] = {}
        self.service_state = 1  # kf/service_state/get 回的会话状态（测试改成 3 看发件员拦不拦）
        self.fail_sync = 0  # 接下来几次 kf/sync_msg 回错误（测试工人重试）

    # ---- 测试里往「客户那边」放消息 ----
    def customer_says(self, external: str, text: str, msgid: str, *, send_time: int | None = None) -> None:
        self.inbox.append({"msgid": msgid, "open_kfid": KFID, "external_userid": external, "send_time": send_time or int(time.time()),
                           "origin": 3, "msgtype": "text", "text": {"content": text}})

    def customer_sends_file(self, external: str, media_id: str, msgid: str, msgtype: str = "file") -> None:
        self.inbox.append({"msgid": msgid, "open_kfid": KFID, "external_userid": external, "send_time": int(time.time()),
                           "origin": 3, "msgtype": msgtype, msgtype: {"media_id": media_id}})

    def enter_session(self, external: str, msgid: str, *, scene_param: str = "", welcome_code: str = "WELCOME",
                      send_time: int | None = None) -> None:
        self.inbox.append({"msgid": msgid, "open_kfid": KFID, "send_time": send_time or int(time.time()), "origin": 4, "msgtype": "event",
                           "event": {"event_type": "enter_session", "open_kfid": KFID, "external_userid": external,
                                     "scene": "gzh", "scene_param": scene_param, "welcome_code": welcome_code}})

    def send_fail_event(self, external: str, fail_msgid: str, msgid: str) -> None:
        self.inbox.append({"msgid": msgid, "open_kfid": KFID, "send_time": int(time.time()), "origin": 4, "msgtype": "event",
                           "event": {"event_type": "msg_send_fail", "open_kfid": KFID, "external_userid": external,
                                     "fail_msgid": fail_msgid, "fail_type": 4}})

    # ---- 假接口 ----
    def handler(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/cgi-bin")
        self.calls.append(path)
        if path == "/gettoken":
            assert request.url.params["corpid"] == CORPID and request.url.params["corpsecret"] == SECRET
            self.tokens_issued += 1
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "access_token": f"TOKEN{self.tokens_issued}", "expires_in": 7200})
        token = request.url.params.get("access_token", "")
        if self.expire_next:
            self.expire_next = False
            return httpx.Response(200, json={"errcode": 42001, "errmsg": "access_token expired"})
        if not token.startswith("TOKEN"):
            return httpx.Response(200, json={"errcode": 40014, "errmsg": "invalid access_token"})
        if path == "/media/get":
            data, name = self.media[request.url.params["media_id"]]
            return httpx.Response(200, content=data, headers={
                "content-type": "application/octet-stream",
                "content-disposition": f"attachment; filename*=UTF-8''{quote(name)}"})
        if path == "/media/upload":
            self.uploads.append({"type": request.url.params["type"], "size": len(request.content)})
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "type": request.url.params["type"],
                                             "media_id": f"UP{len(self.uploads)}", "created_at": str(int(time.time()))})
        body = json.loads(request.content or b"{}")
        if path == "/kf/sync_msg":
            assert body["open_kfid"] == KFID
            if self.fail_sync > 0:
                self.fail_sync -= 1
                return httpx.Response(200, json={"errcode": 95000, "errmsg": "system busy"})
            start = int(body.get("cursor") or 0)
            page = self.inbox[start:start + self.page_size]
            for m in page:
                if m.get("origin") == 3:
                    self.last_customer_time[m["external_userid"]] = m["send_time"]
                    self.sent_since[m["external_userid"]] = 0
            nxt = start + len(page)
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "next_cursor": str(nxt),
                                             "has_more": 1 if nxt < len(self.inbox) else 0, "msg_list": page})
        if path == "/kf/send_msg":
            user = body["touser"]
            last = self.last_customer_time.get(user)
            if last is None or time.time() - last > 48 * 3600 or self.sent_since.get(user, 0) >= 5:
                return httpx.Response(200, json={"errcode": 95002, "errmsg": "invalid msg count or send time"})
            self.sent_since[user] = self.sent_since.get(user, 0) + 1
            self.sent.append(body)
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "msgid": f"SENT{len(self.sent)}"})
        if path == "/kf/send_msg_on_event":
            self.events_sent.append(body)
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "msgid": f"EV{len(self.events_sent)}"})
        if path == "/kf/service_state/trans":
            self.trans.append(body)
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "msg_code": "MSG_CODE"})
        if path == "/kf/service_state/get":
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "service_state": self.service_state, "servicer_userid": ""})
        if path == "/kf/add_contact_way":
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok",
                                             "url": f"https://work.weixin.qq.com/kf/kfcfake?enc_scene={body.get('scene', '')}"})
        if path == "/kf/customer/batchget":
            names = {"wm_hang": "杭杭杭吖", "wm_dlh": "度量海的湛蓝"}
            return httpx.Response(200, json={"errcode": 0, "errmsg": "ok", "customer_list": [
                {"external_userid": u, "nickname": names.get(u, "微信用户")} for u in body["external_userid_list"]]})
        return httpx.Response(404, json={"errcode": -1, "errmsg": "not found"})

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)
