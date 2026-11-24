"""微信客服回调地址：/api/channels/wecom/callback。

- GET：保存回调地址时企业微信来验，1 秒内回解密后的 echostr 明文（凭证配了就能验，不看后台开关）。
- POST：有新消息的通知（加密 XML，里面只有 Token 和 OpenKfId）：只验签、解密、写一行队列、回 success；
  拉消息、认领、回话都在工人里（app/channels/wecom_inbox.py）。官方 5 秒不回会重试 3 次。
  这个处理函数只许调 decrypt_message、parse_xml、enqueue_callback（scripts/check.py 规矩 17）。
凭证没配回 503（还没开通）。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
from wechatpy.exceptions import InvalidSignatureException

from app.core import access
from app.channels.runtime import ChannelsRuntime, channels_dep
from app.channels.wecom import parse_xml
from app.channels.wecom_inbox import enqueue_callback

log = logging.getLogger("app.channels.wecom")

router = APIRouter(prefix="/wecom", tags=["channels"], dependencies=[Depends(access.webhook)])  # 企业微信回调：靠验签


def _crypto(rt: ChannelsRuntime):
    if rt.crypto is None:
        raise HTTPException(503, detail="微信客服还没配置")
    return rt.crypto


@router.get("/callback", response_class=PlainTextResponse)
def verify(
    msg_signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    echostr: str = Query(...),
    rt: ChannelsRuntime = Depends(channels_dep),
) -> PlainTextResponse:
    try:
        plain = _crypto(rt).check_signature(msg_signature, timestamp, nonce, echostr)
    except InvalidSignatureException as e:
        raise HTTPException(403, detail="签名不对") from e
    return PlainTextResponse(plain if isinstance(plain, str) else plain.decode())


@router.post("/callback", response_class=PlainTextResponse)
async def notify(
    request: Request,
    msg_signature: str = Query(...),
    timestamp: str = Query(...),
    nonce: str = Query(...),
    rt: ChannelsRuntime = Depends(channels_dep),
) -> PlainTextResponse:
    body = (await request.body()).decode("utf-8")
    try:
        plain = _crypto(rt).decrypt_message(body, msg_signature, timestamp, nonce)
    except InvalidSignatureException as e:
        raise HTTPException(403, detail="签名不对") from e
    enqueue_callback(rt, parse_xml(plain))
    return PlainTextResponse("success")
