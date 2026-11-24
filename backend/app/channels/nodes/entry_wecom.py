"""entry.wecom 微信客服（出站：排进待发，发件员按窗口和会话状态发；入站在 channels/wecom.py 翻成 InboundMessage）。

默认关：要 Edison 做完企业认证、配好回调域名和凭证、在后台生成兑换用的客服链接、打开开关，才算能用。
"""

from __future__ import annotations

from typing import Any
from urllib.parse import quote

from app.channels import outbound
from app.channels.entries import register_entry
from app.channels.entry_config import load_entry_config
from app.channels.entry_types import EntryCaps, EntrySpec, OutboundMessage, SendResult
from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register

MB = 1024 * 1024
CAPS = EntryCaps(window_hours=48, window_max_sends=5, can_push=False, text_max_bytes=2048,
                 recv_max_bytes={"file": 20 * MB, "image": 2 * MB, "voice": 2 * MB, "video": 10 * MB},
                 send_max_bytes={"file": 20 * MB, "image": 10 * MB}, has_welcome=True)
REDEEM_SCENE = "redeem"
SCENE_PARAM_MAX = 128  # 官方：scene_param urlencode 后不超过 128 字节


def handler(call: NodeCall, data: OutboundMessage) -> NodeResult:
    r = outbound.queue(call, data, send_now=False)
    if r.status == "failed":
        return NodeResult(exit="failed", output=r, detail=r.detail)
    return NodeResult(exit="queued", output=r, detail=r.detail)


def available(db: Any, rt: Any) -> tuple[bool, str]:
    cfg = load_entry_config(db)
    if not cfg.wecom_enabled:
        return False, "微信客服还没开（后台「入口」页的开关）"
    if rt is None or getattr(rt, "wecom", None) is None or getattr(rt, "crypto", None) is None:
        return False, "企业微信凭证没配全"
    if not cfg.wecom_links.get(REDEEM_SCENE):
        return False, "还没生成兑换用的客服链接"
    return True, ""


def resume_link(db: Any, code: str) -> str | None:
    """存好的 scene=redeem 链接，原样一个字不改，只在末尾拼 scene_param（官方：不能改参数，否则进入事件校验不过）。"""
    base = load_entry_config(db).wecom_links.get(REDEEM_SCENE, "")
    if not base:
        return None
    param = quote(code, safe="")
    if len(param.encode()) > SCENE_PARAM_MAX:
        return None
    return f"{base}{'&' if '?' in base else '?'}scene_param={param}"


CARD = NodeCard(
    id="entry.wecom",
    name="微信客服",
    description="客服账号设成「通过 API 管理」后：回调只验签解密入队；工人拉消息、带码进会话就认领、20 秒内用欢迎语发认领结果和清单；"
                "按「客人说话后 48 小时最多 5 条」、只在会话状态 0 / 1 时发；发不了就等客人下次开口补发。默认关。",
    category="入口",
    tech=["FastAPI GET/POST /api/channels/wecom/callback（只验签、解密、写 channels_wecom_inbox、回 success）",
          "wechatpy WeChatCrypto", "httpx WecomClient：kf/sync_msg、kf/send_msg、kf/send_msg_on_event、kf/service_state/get、"
          "kf/add_contact_way、media/get、media/upload", "工人 app/channels/wecom.py、发件员 app/channels/dispatch.py"],
    input_model=OutboundMessage,
    output_model=SendResult,
    exits=[NodeExit(key="queued", label="排进待发（发件员按窗口和会话状态发；发不了等客人再开口补发）", kind="ok"),
           NodeExit(key="failed", label="没有这个会话", kind="fail")],
    config=[".env：WECOM_CORPID、WECOM_KF_SECRET、WECOM_TOKEN、WECOM_AES_KEY、WECOM_OPEN_KFID（底座）",
            "entry_config.wecom_enabled：开关（默认关）", "entry_config.wecom_links.redeem：兑换用的客服链接",
            "entry_config.wecom_reserve_for_delivery：窗口里给交付留几条（默认 2）",
            "entry_config.wecom_welcome_max_age_s：欢迎语凭证多久内还用（默认 15 秒）"],
    emits=["entry.wecom_enter", "entry.welcome_sent", "entry.welcome_failed", "entry.send_deferred", "channels.wecom_send_fail"],
    listens=["无（入站交 entry.route）"],
    replaceable=["同类入口：entry.webchat、以后的小程序（wx.openCustomerServiceChat 进的还是这个客服）"],
    failure="回调只入队、5 秒内回 success；工人失败退避重试 3 次后 node.failed；拉消息 msgid 去重；send_msg 带 msgid（95033 拒重复）；"
            "发前查会话状态，只在 0、1 时发；不转人工（转了接口就发不了）。",
    owner="D",
    status="要改",
)
register(CARD, handler)

register_entry(EntrySpec(
    node_id="entry.wecom", channel="wecom", label="用微信客服继续", caps=CAPS, resume="link",
    available=available, resume_link=resume_link, order=20,
    hint="打开后先发一句话；助手没提到你的订单，就把激活码发过去。",
))
