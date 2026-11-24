"""entry.webchat 网页聊天（出站：一句话进对话；入站在 channels/web.py 翻成 InboundMessage 交 entry.route）。"""

from __future__ import annotations

from app.channels import outbound
from app.channels.entries import register_entry
from app.channels.entry_types import EntryCaps, EntrySpec, OutboundMessage, SendResult
from app.core.nodes import NodeCall, NodeCard, NodeExit, NodeResult, register

CAPS = EntryCaps(window_hours=None, window_max_sends=None, can_push=True, text_max_bytes=None,
                 recv_max_bytes={"file": 50 * 1024 * 1024}, send_max_bytes={}, has_welcome=False)


def handler(call: NodeCall, data: OutboundMessage) -> NodeResult:
    r = outbound.queue(call, data, send_now=True)
    return NodeResult(exit="failed" if r.status == "failed" else "sent", output=r, detail=r.detail)


CARD = NodeCard(
    id="entry.webchat",
    name="网页聊天",
    description="网页里和同一个助手聊，不用登录，/chat/<key> 就是回来的路；能传大文件、随时能发。"
                "出站：一句话直接进对话（页面几秒刷新一次就看到）；入站：网页接口翻成 InboundMessage 交给 entry.route。",
    category="入口",
    tech=["FastAPI /api/channels/web/*（app/channels/web.py）", "React pages/chat/", "订单中枢待发 create_outbox + mark_sent"],
    input_model=OutboundMessage,
    output_model=SendResult,
    exits=[NodeExit(key="sent", label="进对话了（或同一件事发过了）", kind="ok"),
           NodeExit(key="failed", label="没有这个会话", kind="fail")],
    config=["WEB_UPLOAD_MAX_MB：单个文件上限（默认 50）", "entry_config.web_visitor_ip_daily：没认领时同一 IP 每天几条"],
    emits=["intake.outbox_created", "intake.message_sent"],
    listens=["无"],
    replaceable=["同类入口：entry.wecom、以后的小程序"],
    failure="同一件事按 dedupe_key 不发两遍；上传前先问 entry.route，没认领 409 + 固定话术、不写存储。",
    owner="D",
    status="要改",
)
register(CARD, handler)

register_entry(EntrySpec(
    node_id="entry.webchat", channel="web", label="留在网页做", caps=CAPS, resume="claim_here",
    hint="在这个网页里和助手聊、传资料；记下聊天地址，换手机也能回来。", order=10,
))
